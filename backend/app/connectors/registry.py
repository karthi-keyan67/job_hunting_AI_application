from app.connectors.base import ConnectorNotConfigured, JobConnector
from app.connectors.career_page import CareerPageConnector
from app.connectors.gmail_alerts import GmailJobAlertConnector
from app.connectors.portals import UnsupportedPortalConnector
from app.models.jobs import JobSource

PORTALS = {"LINKEDIN", "NAUKRI", "INSTAHYRE", "CUTSHORT", "HIRIST", "INDEED", "WELLFOUND", "FOUNDIT"}


def connector_for(source: JobSource, session=None) -> JobConnector:
    if source.source_type == "CAREER_PAGE":
        return CareerPageConnector(source)
    if source.source_type == "GMAIL_ALERT":
        return GmailJobAlertConnector(source, session)
    if source.source_type in PORTALS or source.source_type == "MANUAL":
        return UnsupportedPortalConnector(source)
    raise ConnectorNotConfigured("Unsupported connector type")


def integration_status(source: JobSource) -> str:
    if source.source_type == "CAREER_PAGE":
        return "CONFIGURED" if source.base_url else "NOT_CONFIGURED"
    if source.source_type == "GMAIL_ALERT":
        from app.core.config import get_settings

        settings = get_settings()
        return "CONFIGURED" if settings.google_oauth_client_id and settings.google_oauth_client_secret else "AWAITING_OAUTH_CREDENTIALS"
    if source.source_type in PORTALS:
        return "AWAITING_AUTHORIZED_API_OR_FEED"
    if source.source_type == "MANUAL":
        return "MANUAL_IMPORT_ONLY"
    return "UNSUPPORTED"
