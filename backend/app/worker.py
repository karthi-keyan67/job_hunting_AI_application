"""Dedicated background process for scheduled automation and notification delivery."""
import asyncio
import logging

from app.services.automation import scheduler_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


async def main():
    await scheduler_loop()


if __name__ == "__main__":
    asyncio.run(main())
