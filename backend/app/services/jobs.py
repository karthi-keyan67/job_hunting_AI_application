import logging
import hashlib
import json
from datetime import UTC, datetime
from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.connectors.base import ConnectorError, ConnectorNotConfigured
from app.connectors.gmail_alerts import GmailJobAlertConnector
from app.connectors.registry import PORTALS, connector_for, integration_status
from app.connectors.security import validate_public_url
from app.models.account import User
from app.models.enums import JobSourceStatus, RunStatus
from app.models.jobs import CollectionRun, Job, JobDuplicate, JobSkill, JobSource
from app.repositories.google_oauth import GoogleOAuthRepository
from app.repositories.portal_connections import record_integration_event
from app.repositories.jobs import JobRepository
from app.schemas.jobs import JobImport, JobSourceCreate, JobSourcePatch, NormalizedJob
from app.services.job_normalization import comparison_key, normalize_job

logger = logging.getLogger(__name__)
SUPPORTED_SOURCES = {"CAREER_PAGE", "GMAIL_ALERT", "MANUAL", *PORTALS}
SECRET_CONFIG_KEYS = {"password", "access_token", "refresh_token", "page_token", "client_secret", "secret", "api_key", "authorization"}


def safe_source_config(configuration: dict) -> dict:
    def visit(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if any(secret_key in str(key).casefold() for secret_key in SECRET_CONFIG_KEYS):
                    raise HTTPException(status_code=422, detail="Credentials cannot be stored in source configuration")
                result[str(key)] = visit(item)
            return result
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value
    return visit(configuration)


def public_source_config(configuration: dict) -> dict:
    def visit(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                normalized_key = str(key).casefold()
                if "page_token" in normalized_key:
                    continue
                result[str(key)] = "[REDACTED]" if any(secret in normalized_key for secret in SECRET_CONFIG_KEYS) else visit(item)
            return result
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value
    return visit(configuration or {})


def validate_source_url(url: str | None) -> None:
    if url is None:
        return
    try:
        validate_public_url(url)
    except ConnectorNotConfigured as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail="A public HTTP or HTTPS URL is required") from exc


def source_response(source: JobSource) -> dict:
    return {
        "id": source.id, "name": source.name, "source_type": source.source_type,
        "base_url": source.base_url, "is_enabled": source.is_enabled,
        "configuration": public_source_config(source.configuration), "last_success_at": source.last_success_at,
        "last_failure_at": source.last_failure_at, "created_at": source.created_at,
        "updated_at": source.updated_at, "integration_status": integration_status(source),
    }


def job_response(job: Job, possible_duplicate: bool = False) -> dict:
    skills_required = [skill.skill_name for skill in job.skills if skill.skill_type == "REQUIRED" or skill.is_required]
    skills_preferred = [skill.skill_name for skill in job.skills if skill.skill_type == "PREFERRED" or not skill.is_required]
    return {
        "id": job.id, "source_id": job.source_id, "source_name": job.source.name,
        "external_id": job.external_id, "title": job.title, "company_name": job.company_name,
        "description": job.description, "employment_type": job.employment_type,
        "experience_min": job.experience_min, "experience_max": job.experience_max,
        "location": job.location, "work_mode": job.work_mode, "salary_min": job.salary_min,
        "salary_max": job.salary_max, "salary_currency": job.salary_currency,
        "salary_period": job.salary_period, "job_url": job.job_url, "apply_url": job.apply_url,
        "posted_at": job.posted_at, "expires_at": job.expires_at, "content_hash": job.content_hash,
        "first_seen_at": job.first_seen_at, "last_seen_at": job.last_seen_at,
        "status": job.status, "required_skills": skills_required,
        "preferred_skills": skills_preferred, "possible_duplicate": possible_duplicate,
        "created_at": job.created_at,
    }


class JobService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = JobRepository(session)

    async def list_sources(self, user_id: UUID) -> list[dict]:
        return [source_response(source) for source in await self.repo.list_sources(user_id)]

    async def create_source(self, user_id: UUID, payload: JobSourceCreate) -> dict:
        source_type = payload.source_type.strip().upper()
        if source_type not in SUPPORTED_SOURCES:
            raise HTTPException(status_code=422, detail="Unsupported source type")
        if source_type == "CAREER_PAGE":
            if not payload.base_url:
                raise HTTPException(status_code=422, detail="A public career page URL is required")
            validate_source_url(payload.base_url)
        config = safe_source_config(payload.configuration)
        if source_type == "GMAIL_ALERT":
            try:
                config = GmailJobAlertConnector.validate_source_configuration(config)
            except ConnectorNotConfigured as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if payload.is_enabled and config.get("platform") != "GENERIC":
                connection = await GoogleOAuthRepository(self.session).get_connection(user_id)
                if connection is None or connection.revoked_at is not None:
                    raise HTTPException(status_code=409, detail="Connect Gmail before enabling alert collection")
        source = JobSource(
            user_id=user_id, name=payload.name.strip(), source_type=source_type, connector_type=source_type,
            base_url=payload.base_url, configuration=config,
            is_enabled=payload.is_enabled and source_type not in PORTALS,
            status=JobSourceStatus.ENABLED if payload.is_enabled and source_type not in PORTALS else JobSourceStatus.DISABLED,
        )
        if source_type == "CAREER_PAGE":
            try:
                connector_for(source).validate_configuration()
            except Exception as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        self.session.add(source)
        if source.source_type == "GMAIL_ALERT":
            record_integration_event(self.session, user_id, str(source.configuration.get("platform", "GENERIC")).upper(),
                                     "ALERT_SOURCE_CREATED", source_id=source.id,
                                     details={"discovery_enabled": source.is_enabled})
        await self.session.commit()
        await self.session.refresh(source)
        return source_response(source)

    async def get_source(self, source_id: UUID, user_id: UUID) -> JobSource:
        source = await self.repo.get_source(source_id, user_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Job source not found")
        return source

    async def update_source(self, source_id: UUID, user_id: UUID, payload: JobSourcePatch) -> dict:
        source = await self.get_source(source_id, user_id)
        values = payload.model_dump(exclude_unset=True)
        if source.source_type in PORTALS and values.get("is_enabled") is True:
            raise HTTPException(status_code=409, detail="This portal remains disabled until an authorized API or feed is configured")
        if values.get("name", "not-set") is None:
            raise HTTPException(status_code=422, detail="Source name cannot be null")
        if "base_url" in values:
            validate_source_url(values["base_url"])
        if "configuration" in values and values["configuration"] is not None:
            values["configuration"] = safe_source_config(values["configuration"])
            if source.source_type == "GMAIL_ALERT":
                try:
                    values["configuration"] = GmailJobAlertConnector.validate_source_configuration(values["configuration"])
                except ConnectorNotConfigured as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
        previous_enabled = source.is_enabled
        previous_platform = str((source.configuration or {}).get("platform", "GENERIC")).upper()
        configuration_changed = "configuration" in values and values["configuration"] != source.configuration
        for key, value in values.items():
            setattr(source, key, value)
        if "is_enabled" in values:
            if source.source_type == "GMAIL_ALERT" and source.is_enabled and str((source.configuration or {}).get("platform", "GENERIC")).upper() != "GENERIC":
                connection = await GoogleOAuthRepository(self.session).get_connection(user_id)
                if connection is None or connection.revoked_at is not None:
                    await self.session.rollback()
                    raise HTTPException(status_code=409, detail="Connect Gmail before enabling alert collection")
            source.status = JobSourceStatus.ENABLED if source.is_enabled else JobSourceStatus.DISABLED
        if source.source_type == "CAREER_PAGE":
            try:
                connector_for(source).validate_configuration()
            except Exception as exc:
                await self.session.rollback()
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        if source.source_type == "GMAIL_ALERT":
            platform = str((source.configuration or {}).get("platform", previous_platform)).upper()
            if configuration_changed:
                record_integration_event(self.session, user_id, platform, "ALERT_CONFIGURATION_UPDATED",
                                         source_id=source.id, details={"changed_fields": ["configuration"]})
            if "is_enabled" in values and previous_enabled != source.is_enabled:
                record_integration_event(self.session, user_id, platform,
                                         "DISCOVERY_ENABLED" if source.is_enabled else "DISCOVERY_DISABLED",
                                         source_id=source.id, details={"enabled": source.is_enabled, "method": "GMAIL_JOB_ALERTS"})
        await self.session.commit()
        await self.session.refresh(source)
        return source_response(source)

    async def delete_source(self, source_id: UUID, user_id: UUID) -> None:
        source = await self.get_source(source_id, user_id)
        if await self.repo.has_jobs(source_id):
            raise HTTPException(status_code=409, detail="Sources with collected jobs cannot be deleted; disable the source instead")
        if source.source_type == "GMAIL_ALERT":
            record_integration_event(self.session, user_id, str(source.configuration.get("platform", "GENERIC")).upper(),
                                     "ALERT_SOURCE_DELETED", source_id=source.id,
                                     details={"discovery_enabled": source.is_enabled})
        await self.session.execute(delete(CollectionRun).where(CollectionRun.source_id == source_id))
        await self.session.delete(source)
        await self.session.commit()

    async def test_source(self, source_id: UUID, user_id: UUID) -> dict:
        source = await self.get_source(source_id, user_id)
        connector = connector_for(source, self.session)
        try:
            connector.validate_configuration()
            jobs = await connector.fetch_jobs()
            return {"status": "ok", "jobs_found": len(jobs), "source_id": str(source.id)}
        except ConnectorNotConfigured as exc:
            return {"status": "not_configured", "detail": str(exc), "source_id": str(source.id)}
        except ConnectorError as exc:
            return {"status": "error", "detail": str(exc), "source_id": str(source.id)}
        except Exception as exc:
            logger.error("Source connectivity test failed source_id=%s exception_type=%s", source.id, type(exc).__name__)
            return {"status": "error", "detail": "Source test failed; check the public page configuration.", "source_id": str(source.id)}

    async def list_jobs(self, user_id: UUID, *, search: str | None = None, location: str | None = None,
                        work_mode: str | None = None, source_id: UUID | None = None,
                        offset: int = 0, limit: int = 50) -> dict:
        jobs, total = await self.repo.list_jobs(user_id, search=search, location=location, work_mode=work_mode,
                                                source_id=source_id, offset=offset, limit=limit)
        return {"items": [job_response(job, await self.repo.has_duplicate(job.id)) for job in jobs], "total": total}

    async def get_job(self, job_id: UUID, user_id: UUID) -> dict:
        job = await self.repo.get_job(job_id, user_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job_response(job, await self.repo.has_duplicate(job.id))

    async def import_job(self, user: User, payload: JobImport) -> dict:
        validate_source_url(payload.job_url)
        validate_source_url(payload.apply_url)
        # Manual links are validated, never fetched by the server.
        source = await self.session.scalar(select(JobSource).where(JobSource.user_id == user.id, JobSource.source_type == "MANUAL").order_by(JobSource.created_at).limit(1))
        if source is None:
            source = JobSource(user_id=user.id, name="Manual imports", source_type="MANUAL", connector_type="MANUAL", is_enabled=True,
                               status=JobSourceStatus.ENABLED, configuration={})
            self.session.add(source)
            await self.session.flush()
        source_values = payload.model_dump()
        stable_key = json.dumps({key: comparison_key(str(value)) for key, value in source_values.items() if value is not None}, sort_keys=True)
        source_record = normalize_job({
            **source_values, "external_id": f"manual:{hashlib.sha256(stable_key.encode()).hexdigest()}",
            "raw_data": {"manual_import": True, "submitted_values": payload.model_dump()},
        }, source)
        job, possible, _created = await self._store(source_record, user.id, source)
        await self.session.commit()
        return await self.get_job(job.id, user.id)

    async def collect_source(self, source_id: UUID, user_id: UUID) -> CollectionRun:
        source = await self.repo.get_source(source_id, user_id, lock=True)
        if source is None:
            raise HTTPException(status_code=404, detail="Job source not found")
        if not source.is_enabled:
            raise HTTPException(status_code=409, detail="Enable this source before collecting jobs")
        connector = connector_for(source, self.session)
        try:
            connector.validate_configuration()
        except ConnectorNotConfigured as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        active_run = await self.session.scalar(
            select(CollectionRun).where(CollectionRun.source_id == source.id, CollectionRun.status == RunStatus.RUNNING).with_for_update()
        )
        if active_run:
            started = active_run.started_at
            if started and started < datetime.now(UTC) - timedelta(minutes=30):
                active_run.status = RunStatus.FAILED
                active_run.completed_at = datetime.now(UTC)
                active_run.finished_at = active_run.completed_at
                active_run.error_message = "Stale collection lock released after the worker stopped responding."
                active_run.error_summary = active_run.error_message
                await self.session.flush()
            else:
                raise HTTPException(status_code=409, detail="A collection is already running for this source")
        run = CollectionRun(source_id=source.id, status=RunStatus.RUNNING)
        self.session.add(run)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(status_code=409, detail="A collection is already running for this source") from exc
        run_id = run.id
        try:
            items = await connector.fetch_jobs()
            run = await self.session.get(CollectionRun, run_id)
            source = await self.repo.get_source(source_id, user_id)
            run.jobs_found = len(items)
            for item in items:
                try:
                    normalized = connector.normalize_job(item)
                except Exception:
                    run.jobs_skipped += 1
                    continue
                if not normalized.title or not normalized.company_name or not normalized.external_id:
                    run.jobs_skipped += 1
                    continue
                job, _, created = await self._store(normalized, user_id, source)
                if job is None:
                    run.jobs_skipped += 1
                elif created:
                    run.jobs_created += 1
                else:
                    run.jobs_updated += 1
            run.status = RunStatus.SUCCEEDED
            run.completed_at = datetime.now(UTC)
            run.finished_at = run.completed_at
            source.last_success_at = run.completed_at
            source.status = JobSourceStatus.ENABLED
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            logger.error("Collection failed source_id=%s exception_type=%s", source_id, type(exc).__name__)
            run = await self.session.get(CollectionRun, run_id)
            source = await self.repo.get_source(source_id, user_id)
            run.status = RunStatus.FAILED
            run.completed_at = datetime.now(UTC)
            run.finished_at = run.completed_at
            run.error_message = connector_for(source, self.session).handle_errors(exc) if source else "Collection failed"
            run.error_summary = run.error_message
            source.last_failure_at = run.completed_at
            source.status = JobSourceStatus.DEGRADED
            await self.session.commit()
        return await self.session.get(CollectionRun, run_id)

    async def _store(self, normalized: NormalizedJob, user_id: UUID, source: JobSource) -> tuple[Job | None, bool, bool]:
        existing = await self.session.scalar(select(Job).where(Job.source_id == source.id, Job.external_id == normalized.external_id).options(selectinload(Job.skills)))
        created = existing is None
        if existing is None:
            existing = Job(source_id=source.id, external_id=normalized.external_id, title=normalized.title,
                           company_name=normalized.company_name, description=normalized.description)
            existing.first_seen_at = datetime.now(UTC)
            self.session.add(existing)
        candidate_values = {
            "title": normalized.title, "company_name": normalized.company_name, "description": normalized.description,
            "employment_type": normalized.employment_type, "experience_min": normalized.experience_min,
            "experience_max": normalized.experience_max, "location": normalized.location, "work_mode": normalized.work_mode,
            "salary_min": normalized.salary_min, "salary_max": normalized.salary_max,
            "salary_currency": normalized.salary_currency, "salary_period": normalized.salary_period,
            "job_url": normalized.job_url, "apply_url": normalized.apply_url, "posted_at": normalized.posted_at,
            "expires_at": normalized.expires_at, "content_hash": normalized.content_hash, "raw_data": normalized.raw_data,
            "metadata_json": normalized.raw_data,
            "last_seen_at": datetime.now(UTC), "status": "ACTIVE",
        }
        for key, value in candidate_values.items():
            setattr(existing, key, value)
        await self.session.flush()

        possible = False
        if created:
            candidates = await self.session.scalars(
                select(Job).join(JobSource, JobSource.id == Job.source_id)
                .where(JobSource.user_id == user_id, Job.source_id != source.id)
                .options(selectinload(Job.source))
            )
            for prior in candidates:
                same_identity = (
                    comparison_key(prior.company_name) == comparison_key(normalized.company_name)
                    and comparison_key(prior.title) == comparison_key(normalized.title)
                    and comparison_key(prior.location) == comparison_key(normalized.location)
                )
                same_url = bool(normalized.apply_url and prior.apply_url and normalized.apply_url.casefold() == prior.apply_url.casefold())
                same_content = bool(normalized.content_hash and prior.content_hash and normalized.content_hash == prior.content_hash)
                if same_identity and (same_url or same_content):
                    possible = True
                    self.session.add(JobDuplicate(job_id=prior.id, duplicate_job_id=existing.id,
                                                  match_reason={"identity_match": True, "same_apply_url": same_url, "same_content_hash": same_content,
                                                                "decision": "REVIEW_ONLY"}))

        await self.session.execute(delete(JobSkill).where(JobSkill.job_id == existing.id))
        required = {skill.casefold(): skill for skill in normalized.required_skills}
        preferred = {skill.casefold(): skill for skill in normalized.preferred_skills if skill.casefold() not in required}
        for skill in required.values():
            self.session.add(JobSkill(job_id=existing.id, skill_name=skill[:120], skill=skill[:120], skill_type="REQUIRED", is_required=True))
        for skill in preferred.values():
            self.session.add(JobSkill(job_id=existing.id, skill_name=skill[:120], skill=skill[:120], skill_type="PREFERRED", is_required=False))
        await self.session.flush()
        return existing, possible, created

    async def runs_for_source(self, source_id: UUID, user_id: UUID) -> list[CollectionRun]:
        await self.get_source(source_id, user_id)
        return await self.repo.runs_for_source(source_id)

    async def all_runs(self, user_id: UUID) -> list[CollectionRun]:
        return await self.repo.all_runs(user_id)
