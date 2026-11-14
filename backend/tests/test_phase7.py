from datetime import UTC, datetime, timedelta

import fitz
import pytest
from sqlalchemy import select

from app.models.applications import Application
from app.models.enums import ApplicationStatus
from app.models.account import User

def _pdf(text: str) -> bytes:
    document = fitz.open()
    document.new_page().insert_text((72, 72), text)
    value = document.tobytes()
    document.close()
    return value


async def _application(client, email="phase7@example.com"):
    registration = await client.post("/api/v1/auth/register", json={"email": email, "password": "correct-horse-battery-1"})
    assert registration.status_code == 201, registration.text
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
    imported = await client.post("/api/v1/jobs/import", headers=headers, json={
        "title": "Platform Engineer", "company_name": "Northwind", "location": "Bengaluru",
        "work_mode": "HYBRID", "job_url": "https://example.com/jobs/platform", "apply_url": "https://example.com/apply/platform",
        "required_skills": ["Python"], "description": "Build Python services and platform tooling.",
    })
    assert imported.status_code == 201, imported.text
    resume = await client.post("/api/v1/resumes", headers=headers, data={"title": "Backend resume"},
                               files={"file": ("resume.pdf", _pdf("Candidate Example\nSkills: Python\nPlatform Engineer"), "application/pdf")})
    assert resume.status_code == 201, resume.text
    version_id = resume.json()["versions"][0]["id"]
    matching = await client.post("/api/v1/matching/run", headers=headers, json={"resume_version_id": version_id})
    assert matching.status_code == 200, matching.text
    job_id = imported.json()["id"]
    match_id = matching.json()["items"][0]["id"]
    approved = await client.post(f"/api/v1/job-reviews/{job_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    application = await client.post("/api/v1/applications", headers=headers,
                                    json={"job_id": job_id, "resume_version_id": version_id, "job_match_id": match_id})
    assert application.status_code == 201, application.text
    return headers, application.json()


@pytest.mark.asyncio
async def test_dashboard_pipeline_and_phase6_status_gates(client):
    headers, application = await _application(client)
    summary = await client.get("/api/v1/dashboard/summary", headers=headers)
    assert summary.status_code == 200, summary.text
    data = summary.json()
    assert data["total_jobs_discovered"] == 1
    assert data["jobs_approved_for_preparation"] == 1
    assert data["applications_in_preparation"] == 1
    assert data["recent_matching_results"][0]["title"] == "Platform Engineer"
    assert data["recent_activity"]
    matched_jobs = await client.get("/api/v1/matching/results?review_status=APPROVED_FOR_PREPARATION", headers=headers)
    assert matched_jobs.status_code == 200, matched_jobs.text
    assert matched_jobs.json()["total"] == 1

    page = await client.get("/api/v1/dashboard/pipeline?search=Northwind&limit=1", headers=headers)
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 1
    view = page.json()["items"][0]
    assert view["match_score"] is not None
    assert view["resume_version"]["version_number"] == 1
    assert view["job"]["company_name"] == "Northwind"

    rejected = await client.patch(f"/api/v1/applications/{application['id']}/status", headers=headers, json={"status": "READY_TO_APPLY"})
    assert rejected.status_code == 409
    rejected = await client.patch(f"/api/v1/applications/{application['id']}/status", headers=headers, json={"status": "APPLIED"})
    assert rejected.status_code == 409
    transition = await client.patch(f"/api/v1/applications/{application['id']}/status", headers=headers, json={"status": "READY_FOR_REVIEW"})
    assert transition.status_code == 200


@pytest.mark.asyncio
async def test_interview_timezone_validation_ownership_and_audit_timeline(client):
    headers, application = await _application(client, "interview-owner@example.com")
    other_headers, _ = await _application(client, "interview-other@example.com")
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    payload = {"application_id": application["id"], "interview_type": "Technical", "scheduled_at": future,
               "timezone": "Asia/Kolkata", "meeting_url": "https://meet.example.com/room"}
    invalid = await client.post("/api/v1/interviews", headers=headers, json={**payload, "scheduled_at": "2026-12-01T10:00:00"})
    assert invalid.status_code == 422
    invalid = await client.post("/api/v1/interviews", headers=headers, json={**payload, "meeting_url": "javascript:alert(1)"})
    assert invalid.status_code == 422

    created = await client.post("/api/v1/interviews", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    interview_id = created.json()["id"]
    assert created.json()["timezone"] == "Asia/Kolkata"
    interview_page = await client.get("/api/v1/interviews?offset=0&limit=1", headers=headers)
    assert interview_page.status_code == 200
    assert interview_page.json()["total"] == 1
    hidden = await client.get(f"/api/v1/interviews/{interview_id}", headers=other_headers)
    assert hidden.status_code == 404
    changed = await client.patch(f"/api/v1/interviews/{interview_id}", headers=headers, json={"status": "COMPLETED", "notes": "Panel completed"})
    assert changed.status_code == 200
    assert changed.json()["status"] == "COMPLETED"

    timeline = await client.get(f"/api/v1/applications/{application['id']}/timeline", headers=headers)
    assert timeline.status_code == 200, timeline.text
    events = timeline.json()["timeline"]
    assert [event["occurred_at"] for event in events] == sorted(event["occurred_at"] for event in events)
    assert any(event["event"] == "JOB_REVIEW_APPROVED_FOR_PREPARATION" for event in events)
    assert any(event["event"] == "APPLICATION_CREATED" for event in events)
    assert any(event["event"] == "INTERVIEW_SCHEDULED" for event in events)
    assert any(event["event"] == "INTERVIEW_COMPLETED" for event in events)

    cancelled = await client.delete(f"/api/v1/interviews/{interview_id}", headers=headers)
    assert cancelled.status_code == 204
    record = await client.get(f"/api/v1/interviews/{interview_id}", headers=headers)
    assert record.json()["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_follow_up_create_complete_overdue_and_isolation(client):
    headers, application = await _application(client, "followup-owner@example.com")
    other_headers, _ = await _application(client, "followup-other@example.com")
    due = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    created = await client.post("/api/v1/follow-ups", headers=headers, json={
        "application_id": application["id"], "title": "Email recruiter", "description": "Ask about next steps.",
        "due_at": due, "timezone": "Asia/Kolkata",
    })
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]
    followup_page = await client.get("/api/v1/follow-ups?offset=0&limit=1", headers=headers)
    assert followup_page.status_code == 200
    assert followup_page.json()["total"] == 1
    overdue = await client.get("/api/v1/follow-ups?overdue=true", headers=headers)
    assert overdue.status_code == 200
    assert overdue.json()["items"][0]["id"] == item_id
    hidden = await client.patch(f"/api/v1/follow-ups/{item_id}", headers=other_headers, json={"status": "COMPLETED"})
    assert hidden.status_code == 404
    completed = await client.patch(f"/api/v1/follow-ups/{item_id}", headers=headers, json={"status": "COMPLETED"})
    assert completed.status_code == 200
    assert completed.json()["completed_at"] is not None
    assert not (await client.get("/api/v1/follow-ups?overdue=true", headers=headers)).json()["items"]
    timeline = await client.get(f"/api/v1/applications/{application['id']}/timeline", headers=headers)
    assert any(event["event"] == "FOLLOW_UP_COMPLETED" for event in timeline.json()["timeline"])


@pytest.mark.asyncio
async def test_analytics_empty_data_and_small_sample_conversion(client):
    registration = await client.post("/api/v1/auth/register", json={"email": "analytics-empty@example.com", "password": "correct-horse-battery-1"})
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
    result = await client.get("/api/v1/analytics/overview", headers=headers)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["application_count"] == 0
    assert data["applications_by_status"] == {}
    assert data["applications_over_time"] == []
    assert data["match_distribution"] == {}
    assert data["interview_conversion"] == {"numerator": 0, "denominator": 0, "percentage": None, "sample_size_sufficient": False}
    assert data["offer_conversion"]["percentage"] is None


@pytest.mark.asyncio
async def test_analytics_conversion_and_source_counts_match_known_postgresql_fixtures(client, db_session):
    headers, first = await _application(client, "analytics-fixture@example.com")
    for index in range(2, 6):
        imported = await client.post("/api/v1/jobs/import", headers=headers, json={
            "title": f"Platform Engineer {index}", "company_name": f"Northwind {index}",
            "job_url": f"https://example.com/jobs/platform-{index}", "apply_url": f"https://example.com/apply/platform-{index}",
            "description": "Build Python platform services.", "required_skills": ["Python"],
        })
        assert imported.status_code == 201, imported.text
        job_id = imported.json()["id"]
        matched = await client.post(f"/api/v1/matching/jobs/{job_id}", headers=headers, json={"resume_version_id": first["resume_version_id"]})
        assert matched.status_code == 200, matched.text
        approved = await client.post(f"/api/v1/job-reviews/{job_id}/approve", headers=headers)
        assert approved.status_code == 200
        created = await client.post("/api/v1/applications", headers=headers, json={
            "job_id": job_id, "resume_version_id": first["resume_version_id"], "job_match_id": matched.json()["id"],
        })
        assert created.status_code == 201, created.text

    owner = await db_session.scalar(select(User).where(User.email == "analytics-fixture@example.com"))
    rows = list(await db_session.scalars(select(Application).where(Application.user_id == owner.id).order_by(Application.created_at)))
    now = datetime.now(UTC)
    for index, row in enumerate(rows):
        row.submitted_at = now - timedelta(days=10 - index)
        row.status = [ApplicationStatus.APPLIED, ApplicationStatus.APPLIED, ApplicationStatus.APPLIED,
                      ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER][index]
    await db_session.commit()

    result = await client.get("/api/v1/analytics/overview", headers=headers)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["application_count"] == 5
    assert data["applications_by_status"] == {"APPLIED": 3, "INTERVIEW": 1, "OFFER": 1}
    assert data["interview_conversion"]["numerator"] == 2
    assert data["interview_conversion"]["denominator"] == 5
    assert data["interview_conversion"]["percentage"] == 40.0
    assert data["offer_conversion"]["numerator"] == 1
    assert data["offer_conversion"]["percentage"] == 20.0
    assert data["source_distribution"] == [{"source": "Manual imports", "count": 5}]
