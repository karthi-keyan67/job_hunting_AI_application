import pytest


async def authenticated_client(client):
    response = await client.post("/api/v1/auth/register", json={"email": "profile@example.com", "password": "correct-horse-battery-1"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_profile_get_and_update(client):
    headers = await authenticated_client(client)
    initial = await client.get("/api/v1/profile", headers=headers)
    assert initial.status_code == 200
    assert initial.json()["full_name"] is None
    updated = await client.put("/api/v1/profile", headers=headers, json={
        "full_name": "Sam Example", "current_designation": "Developer", "current_company": "Example Co",
        "total_experience_months": 30, "notice_period_days": 45,
        "preferred_salary_minimum": 1200000, "preferred_salary_maximum": 1500000,
        "currency": "INR", "bio": "Python backend engineer",
    })
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Sam Example"
    assert updated.json()["total_experience_months"] == 30


@pytest.mark.asyncio
async def test_profile_unauthorized(client):
    response = await client.get("/api/v1/profile")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_preference_get_and_update(client):
    headers = await authenticated_client(client)
    initial = await client.get("/api/v1/preferences", headers=headers)
    assert initial.status_code == 200 and initial.json()["target_job_roles"] == []
    updated = await client.put("/api/v1/preferences", headers=headers, json={
        "target_job_roles": ["Python Backend Developer", "Generative AI Engineer"],
        "required_skills": ["Python", "FastAPI"], "optional_skills": ["React"],
        "minimum_experience_months": 24, "maximum_experience_months": 36,
        "minimum_salary": 1200000, "maximum_salary": 1500000,
        "preferred_locations": ["Chennai", "Remote India"], "work_modes": ["REMOTE", "HYBRID"],
        "excluded_companies": ["Example Restricted Inc"], "is_active": True,
    })
    assert updated.status_code == 200
    assert updated.json()["required_skills"] == ["Python", "FastAPI"]
    assert updated.json()["preferred_locations"] == ["Chennai", "Remote India"]


@pytest.mark.asyncio
async def test_invalid_salary_range_is_rejected(client):
    headers = await authenticated_client(client)
    response = await client.put("/api/v1/profile", headers=headers, json={
        "preferred_salary_minimum": 1500000, "preferred_salary_maximum": 1200000,
    })
    assert response.status_code == 422
