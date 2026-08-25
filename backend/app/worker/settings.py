import logging

from arq.connections import RedisSettings

from app.config import settings
from app.worker.tasks import extract_skill_job, run_experiment_job

logging.basicConfig(level=settings.log_level)


async def startup(ctx) -> None:
    logging.getLogger(__name__).info("worker online, model=%s", settings.openrouter_model)


async def shutdown(ctx) -> None:
    from app.events.bus import bus

    await bus.close()


class WorkerSettings:
    functions = [extract_skill_job, run_experiment_job]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = startup
    on_shutdown = shutdown
    # An analysis run is up to AGENT_MAX_ITERATIONS model calls plus sandbox
    # execution. MEASURED: a single extraction call against stealth/ox-alpha
    # takes 7-8 minutes, so one hour is a safe ceiling, not an expectation.
    job_timeout = 3600
    keep_result = 3600
    max_jobs = 4
    max_tries = 2
