from __future__ import annotations

import logging
import uuid

from app.db.models import Paper, PaperStatus
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def extract_skill_job(ctx, paper_id: str) -> dict:
    """Extract a skill from an already-parsed paper.

    MEASURED against stealth/ox-alpha: 7-8 minutes per paper, which is exactly
    why it lives in a worker and not in the request path.
    """
    from app.agents.skill_extraction.graph import extract_skill_from_paper
    from app.services.papers import load_parsed_pages, persist_skill

    pid = uuid.UUID(paper_id)

    async with AsyncSessionLocal() as session:
        paper = await session.get(Paper, pid)
        if paper is None:
            return {"ok": False, "error": "paper not found"}
        paper.status = PaperStatus.EXTRACTING
        await session.commit()

    try:
        async with AsyncSessionLocal() as session:
            parsed = await load_parsed_pages(session, pid)

        result = await extract_skill_from_paper(parsed, paper_id)

        async with AsyncSessionLocal() as session:
            paper = await session.get(Paper, pid)
            version = await persist_skill(session, paper, result)
            await session.commit()
            return {
                "ok": True,
                "skill_version_id": str(version.id),
                "version": version.version,
                "validation": result.get("validation", {}),
            }
    except Exception as exc:
        logger.exception("skill extraction failed for %s", paper_id)
        async with AsyncSessionLocal() as session:
            paper = await session.get(Paper, pid)
            if paper:
                paper.status = PaperStatus.FAILED
                paper.error = f"{type(exc).__name__}: {exc}"
                await session.commit()
        return {"ok": False, "error": str(exc)}


async def run_experiment_job(ctx, experiment_id: str) -> dict:
    """Runs both arms and the evaluation. Implemented in Plan 05 Task 2.

    The import is function-local on purpose: the worker must start cleanly
    before `app.services.experiments` exists.
    """
    from app.services.experiments import execute_experiment

    return await execute_experiment(uuid.UUID(experiment_id))
