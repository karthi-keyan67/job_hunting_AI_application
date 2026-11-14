import json
import re
from dataclasses import dataclass

from pydantic import ValidationError

from app.schemas.matching import MatchingWeights
from app.services.skill_matching import extract_resume_skills, normalize_skills, overlap_score

SCORING_VERSION = "deterministic-v1"


def configured_weights(raw: str) -> MatchingWeights:
    try:
        value = raw or '{"skills":40,"experience":20,"role":15,"location":15,"salary":10}'
        return MatchingWeights.model_validate(json.loads(value))
    except (ValueError, ValidationError, TypeError) as exc:
        raise ValueError("MATCHING_WEIGHTS must be valid JSON weights totaling 100") from exc


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold()).strip()


def _contains_any(value: str | None, choices: list[str]) -> bool:
    candidate = _norm(value)
    return bool(candidate) and any(_norm(choice) in candidate for choice in choices if _norm(choice))


def _explicit_experience(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?experience", text, re.I)
    if match:
        return int(match.group(1)) * 12
    match = re.search(r"(\d{1,3})\s*\+?\s*months?\s+(?:of\s+)?experience", text, re.I)
    return int(match.group(1)) if match else None


def _salary_yearly(low, high, currency, period, expected_currency):
    if low is None and high is None:
        return None
    if not currency or not expected_currency or currency.casefold() != expected_currency.casefold():
        return None
    period_key = (period or "").casefold()
    multiplier = 12 if period_key in {"month", "monthly", "per month"} else 1 if period_key in {"year", "yearly", "annual", "annually", "per year"} else None
    if multiplier is None:
        return None
    return (float(low) * multiplier if low is not None else None, float(high) * multiplier if high is not None else None)


@dataclass
class DeterministicResult:
    score: float
    confidence: float
    eligibility: str
    criterion_scores: dict[str, float | None]
    available_criteria: list[str]
    missing_criteria: list[str]
    matched_skills: list[str]
    missing_required: list[str]
    missing_preferred: list[str]
    strengths: list[str]
    concerns: list[str]
    explanation: str


def score_match(user, profile, preferences, resume_version, job, weights: MatchingWeights) -> DeterministicResult:
    parsed = resume_version.parsed_data or {}
    resume_text = resume_version.parsed_text or ""
    resume_skills, skill_evidence = extract_resume_skills(resume_text)
    resume_skills.extend(normalize_skills(parsed.get("skills", [])))
    resume_skills = list(dict.fromkeys(resume_skills))

    job_required = [s.skill_name for s in job.skills if s.skill_type == "REQUIRED" or s.is_required]
    job_preferred = [s.skill_name for s in job.skills if s.skill_type == "PREFERRED" or not s.is_required]
    required = normalize_skills([*job_required, *(preferences.required_skills if preferences and preferences.is_active else [])])
    preferred = normalize_skills([*job_preferred, *(preferences.optional_skills if preferences and preferences.is_active else [])])
    matched = [skill for skill in [*required, *preferred] if skill in resume_skills]
    missing_required = [skill for skill in required if skill not in resume_skills]
    missing_preferred = [skill for skill in preferred if skill not in resume_skills]

    scores: dict[str, float | None] = {"skills": None, "experience": None, "role": None, "location": None, "salary": None}
    if resume_version.parsing_status == "COMPLETED" and (required or preferred):
        denominator = sum((2 if skill in required else 1) for skill in [*required, *preferred])
        numerator = sum((2 if skill in required else 1) for skill in matched)
        scores["skills"] = 100 * numerator / denominator if denominator else None

    candidate_experience = profile.total_experience_months if profile and profile.total_experience_months is not None else parsed.get("experience_months") or _explicit_experience(resume_text)
    if candidate_experience is not None and (job.experience_min is not None or job.experience_max is not None):
        if job.experience_min is not None and candidate_experience < job.experience_min:
            gap = job.experience_min - candidate_experience
            scores["experience"] = max(0, 100 - min(100, gap * 2))
        elif job.experience_max is not None and candidate_experience > job.experience_max:
            gap = candidate_experience - job.experience_max
            scores["experience"] = max(0, 100 - min(100, gap))
        else:
            scores["experience"] = 100
    elif candidate_experience is not None and preferences and (preferences.minimum_experience_months is not None or preferences.maximum_experience_months is not None):
        scores["experience"] = 100 if ((preferences.minimum_experience_months is None or candidate_experience >= preferences.minimum_experience_months) and (preferences.maximum_experience_months is None or candidate_experience <= preferences.maximum_experience_months)) else 50

    roles = (preferences.target_job_roles if preferences and preferences.is_active else []) or []
    role_context = roles + ([profile.current_designation] if profile and profile.current_designation else []) + parsed.get("job_titles", [])
    role_score = overlap_score([job.title], role_context)
    if role_score is not None:
        scores["role"] = role_score

    locations = preferences.preferred_locations if preferences and preferences.is_active else []
    work_modes = preferences.work_modes if preferences and preferences.is_active else []
    location_parts = []
    if locations:
        if job.location and _contains_any(job.location, locations):
            location_parts.append(100)
        elif job.location:
            location_parts.append(0)
    if work_modes:
        if job.work_mode and _contains_any(job.work_mode, work_modes):
            location_parts.append(100)
        elif job.work_mode:
            location_parts.append(0)
    if location_parts:
        scores["location"] = sum(location_parts) / len(location_parts)

    expected_min = preferences.minimum_salary if preferences and preferences.is_active else (profile.preferred_salary_minimum if profile else None)
    expected_max = preferences.maximum_salary if preferences and preferences.is_active else (profile.preferred_salary_maximum if profile else None)
    expected_currency = profile.currency if profile else None
    job_range = _salary_yearly(job.salary_min, job.salary_max, job.salary_currency, job.salary_period, expected_currency)
    if (expected_min is not None or expected_max is not None) and job_range is not None:
        # Profile/preference salary bands are treated as annual values; job monthly bands are normalized above.
        pref_low = float(expected_min) if expected_min is not None else None
        pref_high = float(expected_max) if expected_max is not None else None
        job_low, job_high = job_range
        if pref_low is not None and job_high is not None and job_high < pref_low:
            scores["salary"] = 0
        elif pref_high is not None and job_low is not None and job_low > pref_high:
            scores["salary"] = 0
        else:
            scores["salary"] = 100

    weight_map = weights.model_dump()
    available = [name for name, value in scores.items() if value is not None and weight_map[name] > 0]
    missing = [name for name, value in scores.items() if value is None]
    weight_sum = sum(weight_map[name] for name in available)
    overall = sum(scores[name] * weight_map[name] for name in available) / weight_sum if weight_sum else 0.0
    confidence = weight_sum

    hard_mismatch: list[str] = []
    warnings: list[str] = []
    if preferences and preferences.is_active:
        if preferences.excluded_companies and _contains_any(job.company_name, preferences.excluded_companies):
            hard_mismatch.append("Company is on the excluded list")
        if preferences.excluded_roles and _contains_any(job.title, preferences.excluded_roles):
            hard_mismatch.append("Role is on the excluded list")
        if locations and job.location and not _contains_any(job.location, locations):
            hard_mismatch.append("Known job location does not match preferred locations")
        if locations and not job.location:
            warnings.append("Job location is not provided")
        if work_modes and job.work_mode and not _contains_any(job.work_mode, work_modes):
            hard_mismatch.append("Known work mode does not match preferences")
        if preferences.employment_types and job.employment_type and not _contains_any(job.employment_type, preferences.employment_types):
            hard_mismatch.append("Known employment type does not match preferences")
        if preferences.minimum_experience_months is not None or preferences.maximum_experience_months is not None:
            if job.experience_min is not None and preferences.maximum_experience_months is not None and job.experience_min > preferences.maximum_experience_months:
                hard_mismatch.append("Job experience requirement is above the configured range")
            if job.experience_max is not None and preferences.minimum_experience_months is not None and job.experience_max < preferences.minimum_experience_months:
                hard_mismatch.append("Job experience range is below the configured range")
        if work_modes and not job.work_mode:
            warnings.append("Work mode is not provided")
    if missing:
        warnings.append("Some scoring criteria are unavailable: " + ", ".join(missing))
    eligibility = "MISMATCH" if hard_mismatch else "UNKNOWN" if not available else "PARTIAL_MATCH" if warnings else "MATCH"
    strengths = []
    if matched:
        strengths.append("Resume evidence matches: " + ", ".join(matched))
    if scores["experience"] == 100:
        strengths.append("Experience is within the known job range")
    if scores["location"] == 100:
        strengths.append("Known location/work mode aligns with preferences")
    concerns = list(dict.fromkeys([*hard_mismatch, *warnings]))
    details = "; ".join([*strengths, *concerns]) or "Insufficient profile or job data for a confident assessment."
    if available:
        formula = ", ".join(f"{name} {scores[name]:.0f}% × {weight_map[name]:g}%" for name in available)
        skill_note = " Required skills count twice as much as preferred skills within the skills criterion." if scores["skills"] is not None else ""
        explanation = f"Normalized weighted score {overall:.1f}% from available criteria ({formula}); confidence {confidence:.0f}% reflects available configured weight.{skill_note} " + details
    else:
        explanation = "No weighted criteria had sufficient data; score is 0% with 0% confidence. " + details
    return DeterministicResult(round(overall, 2), round(confidence, 2), eligibility, scores, available, missing,
                               matched, missing_required, missing_preferred, strengths, concerns, explanation)
