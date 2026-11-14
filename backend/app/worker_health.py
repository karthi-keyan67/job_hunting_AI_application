import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.database import SessionFactory
from app.models.automation import WorkerHeartbeat


async def check():
    async with SessionFactory() as session:
        row = await session.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.worker_name == "job-collection-worker"))
        if row is None or (datetime.now(UTC) - row.last_heartbeat_at).total_seconds() > 120:
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(check())
