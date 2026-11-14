import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import Application, Job, JobPreference, JobSource, User, UserProfile


@pytest.mark.asyncio
async def test_migrated_schema_can_create_model_rows(db_session):
    user = User(id=uuid.uuid4(), email="model@example.com", password_hash="argon2-hash")
    user.profile = UserProfile(currency="INR")
    user.preferences = JobPreference()
    db_session.add(user)
    await db_session.commit()
    count = await db_session.scalar(select(func.count()).select_from(User))
    assert count == 1
    assert user.profile is not None


@pytest.mark.asyncio
async def test_unique_email_database_constraint(db_session):
    db_session.add_all([
        User(email="duplicate@example.com", password_hash="hash1"),
        User(email="duplicate@example.com", password_hash="hash2"),
    ])
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_source_type_enum_and_json_metadata_persist(db_session):
    source = JobSource(name="Company Careers", connector_type="CAREER_PAGE", configuration={"base_url": "https://careers.example"})
    db_session.add(source)
    await db_session.commit()
    assert source.id is not None
    assert source.configuration["base_url"] == "https://careers.example"


@pytest.mark.asyncio
async def test_duplicate_application_and_invalid_foreign_key_are_rejected(db_session):
    user = User(email="application@example.com", password_hash="hash")
    source = JobSource(name="Careers", connector_type="CAREER_PAGE")
    db_session.add_all([user, source])
    await db_session.flush()
    job = Job(source_id=source.id, external_id="42", title="Backend Developer", company_name="Example", description="Role")
    db_session.add(job)
    await db_session.flush()
    db_session.add_all([Application(user_id=user.id, job_id=job.id), Application(user_id=user.id, job_id=job.id)])
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    invalid_source = JobSource(name="Invalid FK", connector_type="CAREER_PAGE")
    db_session.add(invalid_source)
    await db_session.flush()
    invalid_job = Job(source_id=uuid.uuid4(), external_id="missing", title="Role", company_name="Company", description="Role")
    db_session.add(invalid_job)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
