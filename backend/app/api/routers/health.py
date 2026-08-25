from fastapi import APIRouter
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.db.session import engine
from app.storage.s3 import store

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    """Liveness only. Deliberately touches no dependency so an unhealthy
    database cannot make the container get killed by an orchestrator."""
    return {"status": "ok"}


@router.get("")
async def health() -> dict[str, object]:
    database = redis_ok = storage = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        database = True
    except Exception:
        pass
    try:
        import redis.asyncio as aioredis

        from app.config import settings

        client = aioredis.from_url(settings.redis_url)
        await client.ping()
        await client.aclose()
        redis_ok = True
    except Exception:
        pass
    try:
        # boto3 is synchronous. Called directly it would block the event loop
        # for the full connect timeout whenever storage is down, stalling every
        # other in-flight request on a endpoint that gets polled.
        await run_in_threadpool(store.ensure_bucket)
        storage = True
    except Exception:
        pass

    ok = database and redis_ok and storage
    return {
        "status": "ok" if ok else "degraded",
        "database": database,
        "redis": redis_ok,
        "storage": storage,
    }
