import asyncio
import hashlib
import json
import logging
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from app.core.config import Settings, get_settings
from app.models.jobs import Job, JobMatch
from app.repositories.matching import MatchingRepository
from app.schemas.matching import MatchingWeights
from app.services.ai_matching import PROMPT_VERSION, analyze_match
from app.services.matching_scoring import SCORING_VERSION, configured_weights, score_match
from app.services.skill_matching import normalize_skills

logger = logging.getLogger(__name__)
_ai_semaphore = asyncio.Semaphore(3)
async def enforce_rate_limit(session, user_id: UUID, settings: Settings) -> None:
    await MatchingRepository(session).enforce_rate_limit(user_id, settings.matching_rate_limit_per_minute)


def _fingerprint(user, profile, prefs, version, job, weights: MatchingWeights, *, include_ai: bool, settings: Settings) -> str:
    input_data = {
        "user": str(user.id), "resume_version": str(version.id), "resume_updated": version.updated_at.isoformat() if version.updated_at else None,
        "profile": {key: str(getattr(profile, key)) if getattr(profile, key) is not None else None for key in ("current_designation", "total_experience_months", "preferred_salary_minimum", "preferred_salary_maximum", "currency", "updated_at")},
        "preferences": {key: getattr(prefs, key) for key in ("target_job_roles", "required_skills", "optional_skills", "minimum_experience_months", "maximum_experience_months", "minimum_salary", "maximum_salary", "preferred_locations", "work_modes", "excluded_companies", "excluded_roles", "employment_types", "is_active", "updated_at")} if prefs else {},
        "job": {key: str(getattr(job, key)) if isinstance(getattr(job, key), Decimal) else getattr(job, key) for key in ("id", "title", "company_name", "description", "location", "work_mode", "employment_type", "experience_min", "experience_max", "salary_min", "salary_max", "salary_currency", "salary_period", "content_hash", "updated_at")},
        "job_skills": sorted((skill.skill_name, skill.skill_type, skill.is_required) for skill in job.skills),
        "weights": weights.model_dump(), "scoring_version": SCORING_VERSION,
        "ai": {"enabled": bool(include_ai and settings.matching_ai_enabled and settings.openai_api_key), "model": settings.openai_model if include_ai else None, "prompt": PROMPT_VERSION if include_ai else None},
    }
    serialized = json.dumps(input_data, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def _recommendation(match: JobMatch) -> str:
    if match.eligibility_status == "MISMATCH":
        return "NOT_RECOMMENDED"
    ai_recommendation = (match.ai_analysis or {}).get("recommendation")
    if ai_recommendation in {"APPLY", "REVIEW", "SKIP"}:
        return {"APPLY": "STRONG_MATCH", "REVIEW": "REVIEW", "SKIP": "LOW_MATCH"}[ai_recommendation]
    if match.overall_score >= 75:
        return "STRONG_MATCH"
    return "REVIEW" if match.overall_score >= 45 else "LOW_MATCH"


def match_response(match: JobMatch, job: Job) -> dict:
    return {
        "id": match.id, "job_id": job.id, "resume_version_id": match.resume_version_id,
        "overall_score": float(match.overall_score), "confidence": float(match.confidence), "eligibility_status": match.eligibility_status,
        "skills_score": float(match.skills_score) if match.skills_score is not None else None,
        "experience_score": float(match.experience_score) if match.experience_score is not None else None,
        "role_score": float(match.role_score) if match.role_score is not None else None,
        "location_score": float(match.location_score) if match.location_score is not None else None,
        "salary_score": float(match.salary_score) if match.salary_score is not None else None,
        "criteria_scores": {"skills": float(match.skills_score) if match.skills_score is not None else None,
                            "experience": float(match.experience_score) if match.experience_score is not None else None,
                            "role": float(match.role_score) if match.role_score is not None else None,
                            "location": float(match.location_score) if match.location_score is not None else None,
                            "salary": float(match.salary_score) if match.salary_score is not None else None},
        "available_criteria": (match.details or {}).get("available_criteria", []),
        "missing_criteria": (match.details or {}).get("missing_criteria", []),
        "ai_analysis": match.ai_analysis or {}, "matched_skills": match.matched_skills or [],
        "missing_required_skills": match.missing_required_skills or [],
        "missing_preferred_skills": match.missing_preferred_skills or [], "strengths": match.strengths or [],
        "concerns": match.concerns or [], "explanation": match.explanation, "model_name": match.model_name,
        "prompt_version": match.prompt_version, "scoring_version": match.scoring_version,
        "recommendation": _recommendation(match),
        "job": {"id": str(job.id), "title": job.title, "company_name": job.company_name, "location": job.location,
                "work_mode": job.work_mode, "employment_type": job.employment_type, "salary_min": float(job.salary_min) if job.salary_min is not None else None,
                "salary_max": float(job.salary_max) if job.salary_max is not None else None, "salary_currency": job.salary_currency,
                "salary_period": job.salary_period, "experience_min": job.experience_min, "experience_max": job.experience_max,
                "description": job.description, "job_url": job.job_url, "apply_url": job.apply_url,
                "source_id": str(job.source_id), "source_name": job.source.name,
                "required_skills": [s.skill_name for s in job.skills if s.skill_type == "REQUIRED" or s.is_required],
                "preferred_skills": [s.skill_name for s in job.skills if s.skill_type == "PREFERRED" or not s.is_required]},
        "created_at": match.created_at,
    }


class MatchingService:
    def __init__(self, session, settings: Settings | None = None):
        self.session = session
        self.repo = MatchingRepository(session)
        self.settings = settings or get_settings()

    async def _inputs(self, user_id: UUID, resume_version_id: UUID | None):
        user, profile, prefs, version = await self.repo.load_inputs(user_id, resume_version_id)
        if version is None:
            raise HTTPException(status_code=422, detail="Upload a resume and select a resume version before matching")
        return user, profile, prefs, version

    async def _match_job(self, user, profile, prefs, version, job, weights, include_ai: bool):
        fingerprint = _fingerprint(user, profile, prefs, version, job, weights, include_ai=include_ai, settings=self.settings)
        existing = await self.repo.find_cached(user.id, job.id, fingerprint)
        if existing:
            return existing
        result = score_match(user, profile, prefs, version, job, weights)
        ai_analysis: dict = {"status": "not_configured"} if include_ai and (not self.settings.matching_ai_enabled or not self.settings.openai_api_key) else {}
        model_name = None
        role_score = result.criterion_scores["role"]
        if include_ai and self.settings.matching_ai_enabled and self.settings.openai_api_key:
            required = normalize_skills([s.skill_name for s in job.skills if s.skill_type == "REQUIRED" or s.is_required] + (prefs.required_skills if prefs and prefs.is_active else []))
            preferred = normalize_skills([s.skill_name for s in job.skills if s.skill_type == "PREFERRED" or not s.is_required] + (prefs.optional_skills if prefs and prefs.is_active else []))
            try:
                async with _ai_semaphore:
                    analysis, usage = await analyze_match(self.settings, resume_version=version, job=job, required_skills=required, preferred_skills=preferred)
                ai_analysis = {**analysis, "token_usage": usage, "status": "complete"}
                model_name = self.settings.openai_model
                ai_role_score = float(analysis["role_relevance"])
                role_score = ai_role_score if role_score is None else round(role_score * 0.6 + ai_role_score * 0.4, 2)
                if result.criterion_scores["role"] is None and role_score is not None:
                    result.criterion_scores["role"] = role_score
                    result.available_criteria.append("role")
                    result.missing_criteria = [x for x in result.missing_criteria if x != "role"]
                elif "role" in result.criterion_scores:
                    result.criterion_scores["role"] = role_score
                total_weight = sum(weights.model_dump()[key] for key in result.available_criteria)
                result.score = round(sum(result.criterion_scores[key] * weights.model_dump()[key] for key in result.available_criteria) / total_weight, 2) if total_weight else 0
                result.confidence = round(total_weight, 2)
            except Exception as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                logger.warning("AI matching unavailable for job %s: %s", job.id, type(exc).__name__)
                ai_analysis = {"status": "unavailable", "message": "AI analysis could not be completed; deterministic result shown."}

        details = {"available_criteria": result.available_criteria, "missing_criteria": result.missing_criteria,
                   "criteria_scores": result.criterion_scores, "weights": weights.model_dump(), "score_confidence_basis": "sum of configured weights for available criteria"}
        row = JobMatch(
            user_id=user.id, job_id=job.id, score=result.score, overall_score=result.score, confidence=result.confidence,
            eligibility_status=result.eligibility, skills_score=result.criterion_scores["skills"],
            experience_score=result.criterion_scores["experience"], role_score=result.criterion_scores["role"],
            location_score=result.criterion_scores["location"], salary_score=result.criterion_scores["salary"],
            resume_version_id=version.id, input_fingerprint=fingerprint, ai_analysis=ai_analysis,
            matched_skills=result.matched_skills, missing_required_skills=result.missing_required,
            missing_preferred_skills=result.missing_preferred,
            strengths=list(dict.fromkeys(result.strengths + ai_analysis.get("strengths", []))),
            concerns=list(dict.fromkeys(result.concerns + ai_analysis.get("concerns", []) + ([ai_analysis.get("explanation")] if ai_analysis.get("explanation") else []))),
            explanation=result.explanation + (f" AI analysis: {ai_analysis['explanation']}" if ai_analysis.get("explanation") else ""),
            model_name=model_name, prompt_version=PROMPT_VERSION if include_ai else "phase5-v1",
            scoring_version=SCORING_VERSION, details=details,
        )
        return await self.repo.save_idempotent(row)

    async def run(self, user_id: UUID, *, resume_version_id: UUID | None = None, job_ids: list[UUID] | None = None, include_ai: bool = False):
        await enforce_rate_limit(self.session, user_id, self.settings)
        weights = configured_weights(self.settings.matching_weights)
        jobs = await self.repo.list_owned_jobs(user_id, job_ids, self.settings.matching_max_batch)
        user, profile, prefs, version = await self._inputs(user_id, resume_version_id)
        ai_budget = self.settings.matching_max_ai_calls if include_ai else 0
        results = []
        for index, job in enumerate(jobs):
            row = await self._match_job(user, profile, prefs, version, job, weights, include_ai=bool(include_ai and index < ai_budget))
            results.append(match_response(row, job))
        await self.session.commit()
        results.sort(key=lambda item: (item["overall_score"], item["confidence"]), reverse=True)
        return {"items": results, "total": len(results)}

    async def one(self, user_id: UUID, job_id: UUID, *, resume_version_id: UUID | None = None, include_ai: bool = False):
        result = await self.run(user_id, resume_version_id=resume_version_id, job_ids=[job_id], include_ai=include_ai)
        return result["items"][0]

    async def results(self, user_id: UUID, *, min_score: float | None = None, location: str | None = None,
                      work_mode: str | None = None, skill: str | None = None, source_id: UUID | None = None,
                      eligibility: str | None = None, recommendation: str | None = None, review_status: str | None = None, offset: int = 0, limit: int = 50):
        wanted_skill = normalize_skills([skill])[0] if skill else None
        rows = await self.repo.list_results(user_id, min_score=min_score, location=location, work_mode=work_mode,
                                            skill=wanted_skill, source_id=source_id, eligibility=eligibility, review_status=review_status)
        filtered = []
        for match, job in rows:
            response = match_response(match, job)
            if recommendation and response["recommendation"] != recommendation.upper():
                continue
            filtered.append(response)
        return {"items": filtered[offset:offset + limit], "total": len(filtered)}

    async def result(self, user_id: UUID, match_id: UUID):
        pair = await self.repo.get_owned_result(user_id, match_id)
        if pair is None:
            raise HTTPException(status_code=404, detail="Match not found")
        return match_response(*pair)

    async def summary(self, user_id: UUID):
        rows = await self.repo.list_matches(user_id)
        eligibility: dict[str, int] = {}
        recommendations: dict[str, int] = {}
        for row in rows:
            eligibility[row.eligibility_status] = eligibility.get(row.eligibility_status, 0) + 1
            value = _recommendation(row)
            recommendations[value] = recommendations.get(value, 0) + 1
        return {"total": len(rows), "average_score": round(sum(float(x.overall_score) for x in rows) / len(rows), 2) if rows else None,
                "average_confidence": round(sum(float(x.confidence) for x in rows) / len(rows), 2) if rows else None,
                "eligibility": eligibility, "recommendations": recommendations}
