import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app.api.routers import (
    conversations,
    datasets,
    events,
    experiments,
    health,
    papers,
)
from app.config import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.s3_ensure_bucket_on_startup:
        try:
            from app.storage.s3 import store

            # boto3 is synchronous and retries with backoff, so an unreachable
            # object store would otherwise hold the event loop through several
            # attempts before the API accepts its first request. The wait_for
            # bounds boot time; the orphaned thread finishes harmlessly.
            await asyncio.wait_for(
                run_in_threadpool(store.ensure_bucket),
                timeout=settings.s3_startup_timeout_s,
            )
            logger.info("object storage bucket ready: %s", settings.s3_bucket)
        except TimeoutError:
            logger.warning(
                "object storage did not respond within %ss; continuing without "
                "a verified bucket",
                settings.s3_startup_timeout_s,
            )
        except Exception as exc:  # storage may lag behind api on cold start
            logger.warning("could not ensure bucket at startup: %s", exc)
    yield


app = FastAPI(
    title="Scientific Skill Transfer Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://frontend:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(papers.router)
app.include_router(datasets.router)
app.include_router(experiments.router)
app.include_router(conversations.router)
app.include_router(events.router)
