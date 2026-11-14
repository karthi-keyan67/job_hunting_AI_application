from abc import ABC, abstractmethod
from typing import Any

from app.models.jobs import JobSource
from app.schemas.jobs import NormalizedJob


class ConnectorError(RuntimeError):
    """A safe-to-report connector failure."""


class ConnectorNotConfigured(ConnectorError):
    pass


class JobConnector(ABC):
    def __init__(self, source: JobSource):
        self.source = source

    @abstractmethod
    def validate_configuration(self) -> None: ...

    @abstractmethod
    async def fetch_jobs(self) -> list[dict[str, Any]]: ...

    def normalize_job(self, item: dict[str, Any]) -> NormalizedJob:
        from app.services.job_normalization import normalize_job
        return normalize_job(item, self.source)

    def get_source_metadata(self) -> dict[str, Any]:
        return {"source_id": str(self.source.id), "source_name": self.source.name, "source_type": self.source.source_type}

    @staticmethod
    def handle_errors(exc: Exception) -> str:
        # Never echo configuration, credentials, response bodies, or tokens.
        return str(exc)[:500] if isinstance(exc, ConnectorError) else "Connector request failed"
