from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import ConnectorNotConfigured
from app.connectors.gmail_alerts import GmailJobAlertConnector
from app.models.enums import JobSourceStatus
from app.models.jobs import JobSource
from app.repositories.google_oauth import GoogleOAuthRepository
from app.repositories.portal_connections import PortalConnectionRepository, record_integration_event
from app.services.google_oauth import GoogleOAuthService


PLATFORM_DETAILS = {
    "LINKEDIN": {"name": "LinkedIn", "mark": "in", "direct_status": "NOT_AVAILABLE_FOR_JOB_SEEKER", "limitation": "No public job-search API for a job-seeker account was verified. Use LinkedIn job-alert emails."},
    "NAUKRI": {"name": "Naukri", "mark": "N", "direct_status": "NOT_DOCUMENTED", "limitation": "No official individual job-search API or permitted public feed was verified. Use Naukri job-alert emails."},
    "INDEED": {"name": "Indeed", "mark": "Indeed", "direct_status": "PARTNER_API_ONLY", "limitation": "Indeed job-search API access is partner-provisioned; this is not a self-service job-seeker account connection. Use job-alert emails unless partner access is approved."},
    "INSTAHYRE": {"name": "Instahyre", "mark": "I", "direct_status": "NOT_DOCUMENTED", "limitation": "No official job-seeker search API or permitted public feed was verified. Use matching job-alert emails."},
    "CUTSHORT": {"name": "Cutshort", "mark": "C", "direct_status": "API_SCOPE_UNCONFIRMED", "limitation": "Published API materials describe hiring workflows; candidate-side job discovery access is unconfirmed. Use candidate job-alert emails."},
    "HIRIST": {"name": "Hirist", "mark": "H", "direct_status": "NOT_DOCUMENTED", "limitation": "No official job-seeker API or authorized machine-readable feed was verified. Use job-alert emails."},
}


class PortalConnectionsService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = PortalConnectionRepository(session)

    @staticmethod
    def validate_platform(platform: str) -> str:
        normalized = platform.strip().upper()
        if normalized not in PLATFORM_DETAILS:
            raise HTTPException(status_code=404, detail="Job portal integration not found")
        return normalized

    async def overview(self, user_id: UUID) -> dict:
        gmail = await GoogleOAuthService(self.session).status(user_id)
        sources = await self.repo.alert_sources(user_id)
        source_map = {}
        for source in sources:
            platform = str(source.configuration.get("platform", "")).upper()
            source_map.setdefault(platform, source)
        items = []
        for platform, details in PLATFORM_DETAILS.items():
            source = source_map.get(platform)
            runs = await self.repo.runs(source.id, 1) if source else []
            last_run = runs[0] if runs else None
            if not source:
                alert_status = "NOT_CONFIGURED"
            elif not gmail["connected"]:
                alert_status = "GMAIL_NOT_CONNECTED"
            elif source.is_enabled:
                alert_status = "ENABLED"
            else:
                alert_status = "DISABLED"
            items.append({
                "platform": platform,
                **details,
                "connection_method": "GMAIL_JOB_ALERTS",
                "portal_account_connected": False,
                "alert_source_configured": source is not None,
                "source_id": str(source.id) if source else None,
                "discovery_enabled": bool(source and source.is_enabled),
                "can_enable_discovery": bool(source and gmail["connected"]),
                "alert_status": alert_status,
                "allowed_senders": list((source.configuration or {}).get("allowed_senders", [])) if source else [],
                "required_terms": list((source.configuration or {}).get("required_terms", [])) if source else [],
                "label_ids": list((source.configuration or {}).get("label_ids", [])) if source else [],
                "last_success_at": source.last_success_at if source else None,
                "last_failure_at": source.last_failure_at if source else None,
                "last_run": self._run(last_run) if last_run else None,
            })
        return {"gmail": {"connected": gmail["connected"], "gmail_address": gmail.get("gmail_address"),
                           "scopes": gmail.get("scopes", []), "oauth_configured": gmail["oauth_configured"],
                           "oauth_configuration_message": gmail["oauth_configuration_message"]}, "items": items}

    @staticmethod
    def _run(run) -> dict:
        return {"id": str(run.id), "started_at": run.started_at, "completed_at": run.completed_at,
                "status": run.status.value, "jobs_found": run.jobs_found, "jobs_created": run.jobs_created,
                "jobs_updated": run.jobs_updated, "jobs_skipped": run.jobs_skipped,
                "retry_count": run.retry_count, "error": run.error_summary or run.error_message}

    async def save_alert_source(self, user_id: UUID, platform: str, values: dict) -> dict:
        platform = self.validate_platform(platform)
        configuration = {"platform": platform, **values}
        try:
            configuration = GmailJobAlertConnector.validate_source_configuration(configuration)
        except ConnectorNotConfigured as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        source = await self.repo.source_for_platform(user_id, platform)
        created = source is None
        fields = ["allowed_senders", "required_terms", "label_ids"]
        enabled = bool(source and source.is_enabled)
        if created:
            source = JobSource(user_id=user_id, name=f"{PLATFORM_DETAILS[platform]['name']} job alerts",
                               source_type="GMAIL_ALERT", connector_type="GMAIL_ALERT", configuration=configuration,
                               is_enabled=False, status=JobSourceStatus.DISABLED)
            self.session.add(source)
            await self.session.flush()
        else:
            source.configuration = configuration
        record_integration_event(self.session, user_id, platform,
                                 "ALERT_SOURCE_CREATED" if created else "ALERT_CONFIGURATION_UPDATED",
                                 source_id=source.id, details={"changed_fields": fields, "discovery_enabled": enabled})
        await self.session.commit()
        await self.session.refresh(source)
        return await self._item(user_id, platform)

    async def set_discovery(self, user_id: UUID, platform: str, enabled: bool) -> dict:
        platform = self.validate_platform(platform)
        source = await self.repo.source_for_platform(user_id, platform)
        if source is None:
            raise HTTPException(status_code=409, detail="Configure an alert sender before enabling discovery")
        if enabled:
            connection = await GoogleOAuthRepository(self.session).get_connection(user_id)
            if connection is None or connection.revoked_at is not None:
                raise HTTPException(status_code=409, detail="Connect Gmail before enabling alert collection")
        changed = source.is_enabled != enabled
        source.is_enabled = enabled
        source.status = JobSourceStatus.ENABLED if enabled else JobSourceStatus.DISABLED
        if changed:
            record_integration_event(self.session, user_id, platform,
                                     "DISCOVERY_ENABLED" if enabled else "DISCOVERY_DISABLED",
                                     source_id=source.id, details={"enabled": enabled, "method": "GMAIL_JOB_ALERTS"})
        await self.session.commit()
        return await self._item(user_id, platform)

    async def _item(self, user_id: UUID, platform: str) -> dict:
        return next(item for item in (await self.overview(user_id))["items"] if item["platform"] == platform)

    async def history(self, user_id: UUID, platform: str, limit: int = 20) -> dict:
        platform = self.validate_platform(platform)
        source = await self.repo.source_for_platform(user_id, platform)
        if source is None:
            return {"platform": platform, "items": []}
        runs = await self.repo.runs(source.id, limit)
        return {"platform": platform, "items": [self._run(run) for run in runs]}

    async def audit(self, user_id: UUID, platform: str | None, limit: int, offset: int) -> list[dict]:
        if platform:
            platform = platform.strip().upper()
            if platform != "GMAIL":
                platform = self.validate_platform(platform)
        events = await self.repo.audit(user_id, platform=platform, limit=limit, offset=offset)
        return [{"id": str(event.id), "platform": event.platform, "action": event.action,
                 "details": event.details, "occurred_at": event.occurred_at,
                 "source_id": str(event.source_id) if event.source_id else None} for event in events]
