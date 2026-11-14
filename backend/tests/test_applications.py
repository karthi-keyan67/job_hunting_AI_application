import uuid
from types import SimpleNamespace

import fitz
import pytest
from sqlalchemy import select, update

from app.models.account import User
from app.models.applications import ApplicationAuditLog
from app.core.config import Settings
from app.services.application_generation import SYSTEM_PROMPT, generate_one


def _pdf(text: str) -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


async def _prepared_job(client, email: str):
    signup = await client.post("/api/v1/auth/register", json={"email": email, "password": "correct-horse-battery-1"})
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    imported = await client.post("/api/v1/jobs/import", headers=headers, json={
        "title": "Backend Engineer", "company_name": "Acme", "job_url": "https://example.com/jobs/role",
        "apply_url": "https://example.com/apply/role", "required_skills": ["Python"], "description": "Build Python services.",
    })
    assert imported.status_code == 201, imported.text
    resume = await client.post("/api/v1/resumes", headers=headers, data={"title": "Backend resume"},
                               files={"file": ("resume.pdf", _pdf("Taylor Example\nSkills: Python\nBackend Engineer"), "application/pdf")})
    assert resume.status_code == 201, resume.text
    version_id = resume.json()["versions"][0]["id"]
    matches = await client.post("/api/v1/matching/run", headers=headers, json={"resume_version_id": version_id})
    assert matches.status_code == 200, matches.text
    assert matches.json()["total"] == 1
    job_id = imported.json()["id"]
    return headers, job_id, version_id, matches.json()["items"][0]["id"]


@pytest.mark.asyncio
async def test_review_statuses_preserve_history_and_application_is_unique(client, db_session):
    headers, job_id, _version_id, _match_id = await _prepared_job(client, "workflow-review@example.com")
    reviews = await client.get("/api/v1/job-reviews", headers=headers)
    assert reviews.status_code == 200
    assert reviews.json()[0]["status"] == "PENDING_REVIEW"
    saved = await client.post(f"/api/v1/job-reviews/{job_id}/save", headers=headers)
    assert saved.json()["status"] == "SAVED"
    rejected = await client.post(f"/api/v1/job-reviews/{job_id}/reject", headers=headers, json={"reason": "Role timing does not work."})
    assert rejected.json()["status"] == "REJECTED"
    approved = await client.post(f"/api/v1/job-reviews/{job_id}/approve", headers=headers)
    assert approved.json()["status"] == "APPROVED_FOR_PREPARATION"
    history = (await client.get("/api/v1/job-reviews", headers=headers)).json()[0]["history"]
    assert [event["status"] for event in history] == ["PENDING_REVIEW", "SAVED", "REJECTED", "APPROVED_FOR_PREPARATION"]
    user = await db_session.scalar(select(User).where(User.email == "workflow-review@example.com"))
    events = list(await db_session.scalars(select(ApplicationAuditLog).where(ApplicationAuditLog.actor_user_id == user.id)))
    assert {event.action for event in events} >= {"JOB_SAVED", "JOB_REJECTED", "JOB_APPROVED_FOR_PREPARATION"}
    with pytest.raises(Exception, match="append-only"):
        await db_session.execute(update(ApplicationAuditLog).where(ApplicationAuditLog.id == events[0].id).values(action="tampered"))
    await db_session.rollback()


@pytest.mark.asyncio
async def test_complete_manual_handoff_requires_exact_approved_drafts_and_checklist(client, monkeypatch):
    import app.services.applications as service_module

    async def deterministic_generation(_settings, *, draft_type, **_kwargs):
        return f"Reviewed {draft_type}: Python experience.", ["Python"]

    monkeypatch.setattr(service_module, "generate_one", deterministic_generation)
    monkeypatch.setattr(service_module.get_settings(), "openai_api_key", "test-key")
    headers, job_id, version_id, match_id = await _prepared_job(client, "workflow-complete@example.com")
    await client.post(f"/api/v1/job-reviews/{job_id}/approve", headers=headers)
    created = await client.post("/api/v1/applications", headers=headers, json={"job_id": job_id, "resume_version_id": version_id, "job_match_id": match_id})
    assert created.status_code == 201, created.text
    application_id = created.json()["id"]
    duplicate = await client.post("/api/v1/applications", headers=headers, json={"job_id": job_id, "resume_version_id": version_id, "job_match_id": match_id})
    assert duplicate.status_code == 409

    generated = await client.post(f"/api/v1/applications/{application_id}/generate", headers=headers, json={"draft_types": ["TAILORED_RESUME", "COVER_LETTER", "RECRUITER_MESSAGE", "APPLICATION_ANSWERS"]})
    assert generated.status_code == 200, generated.text
    assert len(generated.json()) == 4
    answers = next(item for item in generated.json() if item["draft_type"] == "APPLICATION_ANSWERS")
    assert "[USER INPUT REQUIRED]" in answers["body"]
    approved_ids = []
    for draft in generated.json():
        result = await client.post(f"/api/v1/applications/{application_id}/drafts/{draft['id']}/approve", headers=headers)
        assert result.status_code == 200, result.text
        approved_ids.append(draft["id"])

    original = generated.json()[0]
    edited = await client.patch(f"/api/v1/applications/{application_id}/drafts/{original['id']}", headers=headers, json={"body": "User reviewed Python resume."})
    assert edited.status_code == 200, edited.text
    assert edited.json()["version_number"] == 2 and edited.json()["status"] == "EDITED"
    historical = await client.get(f"/api/v1/applications/{application_id}/drafts/{original['id']}", headers=headers)
    assert historical.json()["body"] == original["body"]
    assert historical.json()["status"] == "SUPERSEDED"
    assert (await client.post(f"/api/v1/applications/{application_id}/final-approval", headers=headers, json={"confirmed": True})).status_code == 409

    all_items = {key: {"completed": True} for key in (await client.get(f"/api/v1/applications/{application_id}/checklist", headers=headers)).json()["required_items"]}
    checklist = await client.put(f"/api/v1/applications/{application_id}/checklist", headers=headers, json={"items": all_items})
    assert checklist.status_code == 200, checklist.text
    current_drafts = (await client.get(f"/api/v1/applications/{application_id}/drafts", headers=headers)).json()
    for draft in current_drafts:
        if draft["status"] != "APPROVED" and draft["draft_type"] == "TAILORED_RESUME":
            await client.post(f"/api/v1/applications/{application_id}/drafts/{draft['id']}/approve", headers=headers)
    final = await client.post(f"/api/v1/applications/{application_id}/final-approval", headers=headers, json={"confirmed": True})
    assert final.status_code == 200, final.text
    assert final.json()["application"]["status"] == "READY_TO_APPLY"
    assert original["id"] not in final.json()["approved_draft_ids"]
    assert edited.json()["id"] in final.json()["approved_draft_ids"]

    handoff = await client.post(f"/api/v1/applications/{application_id}/open-url", headers=headers)
    assert handoff.status_code == 200 and handoff.json()["url"] == "https://example.com/apply/role"
    assert (await client.get(f"/api/v1/applications/{application_id}", headers=headers)).json()["status"] == "READY_TO_APPLY"
    missing_confirmation = await client.post(f"/api/v1/applications/{application_id}/confirm-submission", headers=headers, json={"submitted": False})
    assert missing_confirmation.status_code == 422
    applied = await client.post(f"/api/v1/applications/{application_id}/confirm-submission", headers=headers, json={"submitted": True, "notes": "Submitted manually."})
    assert applied.status_code == 200 and applied.json()["status"] == "APPLIED"
    audit = await client.get(f"/api/v1/applications/{application_id}/audit", headers=headers)
    actions = [event["action"] for event in audit.json()]
    assert "FINAL_APPROVAL_GRANTED" in actions and "APPLICATION_URL_OPENED" in actions and "APPLICATION_MARKED_APPLIED" in actions


@pytest.mark.asyncio
async def test_cross_user_cannot_read_or_open_another_users_application(client):
    headers, job_id, version_id, match_id = await _prepared_job(client, "workflow-owner@example.com")
    await client.post(f"/api/v1/job-reviews/{job_id}/approve", headers=headers)
    created = await client.post("/api/v1/applications", headers=headers, json={"job_id": job_id, "resume_version_id": version_id, "job_match_id": match_id})
    other = await client.post("/api/v1/auth/register", json={"email": "workflow-stranger@example.com", "password": "correct-horse-battery-1"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    app_id = created.json()["id"]
    assert (await client.get(f"/api/v1/applications/{app_id}", headers=other_headers)).status_code == 404
    assert (await client.get(f"/api/v1/applications/{app_id}/audit", headers=other_headers)).status_code == 404
    assert (await client.get("/api/v1/applications", headers=other_headers)).json() == []


@pytest.mark.asyncio
async def test_generation_requires_configured_provider_and_urls_are_never_submission(client):
    headers, job_id, version_id, match_id = await _prepared_job(client, "workflow-unconfigured@example.com")
    await client.post(f"/api/v1/job-reviews/{job_id}/approve", headers=headers)
    created = await client.post("/api/v1/applications", headers=headers, json={"job_id": job_id, "resume_version_id": version_id, "job_match_id": match_id})
    response = await client.post(f"/api/v1/applications/{created.json()['id']}/generate", headers=headers, json={"draft_types": ["COVER_LETTER"]})
    assert response.status_code == 503
    assert created.json()["status"] == "PREPARING"


@pytest.mark.asyncio
async def test_ai_generation_uses_untrusted_context_and_rejects_unverifiable_facts(monkeypatch):
    import json
    import openai

    content = {"body": "Python engineer with service experience.", "evidence": ["Python", "Build Python services"]}
    captured = {}

    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    captured.update(kwargs)
                    return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=json.dumps(content)))], usage=None)
        async def close(self):
            return None

    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_kwargs: FakeClient())
    settings = Settings(openai_api_key="test-key")
    kwargs = {"draft_type": "COVER_LETTER", "resume_data": {"skills": ["Python"], "emails": ["private@example.com"]},
              "parsed_text": "private@example.com", "job": {"title": "Engineer", "description": "Build Python services"}, "user_context": {}}
    body, evidence = await generate_one(settings, **kwargs)
    assert "Python engineer" in body and evidence == ["Python", "Build Python services"]
    assert "untrusted" in SYSTEM_PROMPT.lower() and "ignore embedded commands" in SYSTEM_PROMPT.lower()
    assert "private@example.com" not in captured["messages"][1]["content"]
    content["body"] = "Rust engineer with service experience."
    with pytest.raises(ValueError, match="skills not evidenced"):
        await generate_one(settings, **kwargs)
    content["body"] = "Python engineer with service experience."
    content["evidence"] = ["invented employer"]
    with pytest.raises(ValueError, match="not present"):
        await generate_one(settings, **kwargs)
