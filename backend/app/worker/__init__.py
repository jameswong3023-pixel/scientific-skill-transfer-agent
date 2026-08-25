from arq import create_pool
from arq.connections import RedisSettings

from app.config import settings


async def enqueue(job_name: str, *args) -> str:
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        job = await pool.enqueue_job(job_name, *args)
        return job.job_id if job else ""
    finally:
        await pool.aclose()
