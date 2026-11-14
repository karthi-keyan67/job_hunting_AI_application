from app.connectors.base import ConnectorNotConfigured, JobConnector


class UnsupportedPortalConnector(JobConnector):
    """Explicitly reports portals without an authorized feed/API instead of scraping them."""

    def validate_configuration(self) -> None:
        raise ConnectorNotConfigured(f"{self.source.source_type} has no authorized API or permitted feed configured")

    async def fetch_jobs(self) -> list[dict]:
        self.validate_configuration()
        return []
