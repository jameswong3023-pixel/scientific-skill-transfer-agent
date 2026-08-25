"""Persistent LangGraph run state, backed by Postgres.

Each analysis run checkpoints against a thread keyed by its `Run.id`, so the
graph's state at every super-step survives a worker restart and can be
inspected after the fact rather than living only in process memory.

Checkpointing is deliberately best-effort. If Postgres is unreachable or the
checkpoint tables cannot be created, an analysis run must still execute -- the
experiment is the product, and losing resumability is far cheaper than losing
the run. Callers get None and the graph compiles without a checkpointer.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.config import settings

logger = logging.getLogger(__name__)


def checkpoint_dsn() -> str:
    """Convert the SQLAlchemy URL into something libpq will accept.

    SQLAlchemy encodes its driver in the scheme (postgresql+psycopg://), which
    is a SQLAlchemy convention, not a libpq one. psycopg rejects it outright, so
    the suffix has to come off before the DSN reaches the checkpointer.
    """
    url = settings.sync_database_url
    for prefix in ("postgresql+psycopg://", "postgresql+asyncpg://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


@asynccontextmanager
async def analysis_checkpointer() -> AsyncIterator[object | None]:
    """Yield a ready AsyncPostgresSaver, or None if one cannot be established.

    Never raises. A run without a checkpointer behaves exactly as before.
    """
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except Exception as exc:  # dependency missing or incompatible
        logger.warning("checkpointing unavailable, continuing without it: %s", exc)
        yield None
        return

    try:
        async with AsyncPostgresSaver.from_conn_string(checkpoint_dsn()) as saver:
            # Creates the checkpoint tables on first use; idempotent afterwards.
            await saver.setup()
            logger.info("langgraph checkpointing enabled")
            yield saver
            return
    except Exception as exc:
        logger.warning("could not start checkpointer, continuing without it: %s", exc)

    yield None
