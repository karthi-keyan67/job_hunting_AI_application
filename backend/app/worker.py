"""One-shot worker entrypoint. No recurring schedule is enabled by Phase 4."""
import asyncio

from sqlalchemy import select

from app.core.database import SessionFactory
from app.models.jobs import JobSource
from app.services.jobs import JobService


async def collect_enabled_sources() -> list[dict]:
    async with SessionFactory() as session:
        sources = await session.execute(select(JobSource.id, JobSource.user_id).where(JobSource.is_enabled.is_(True), JobSource.user_id.is_not(None)))
        targets = list(sources.all())
    results = []
    for source_id, user_id in targets:
        async with SessionFactory() as session:
            try:
                run = await JobService(session).collect_source(source_id, user_id)
                results.append({"source_id": str(source_id), "run_id": str(run.id), "status": run.status.value})
            except Exception as exc:
                # Keep processing other configured sources after one source-level failure.
                results.append({"source_id": str(source_id), "status": "FAILED", "error_type": type(exc).__name__})
    return results


if __name__ == "__main__":
    print(asyncio.run(collect_enabled_sources()))
