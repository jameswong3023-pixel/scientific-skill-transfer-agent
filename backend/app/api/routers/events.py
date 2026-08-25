"""Server-sent progress streams.

Subscribe-then-replay: history comes from Postgres, live updates from Redis.
A client that opens the stream mid-run, or reconnects after a network blip,
sees the complete timeline with no gap and no duplicate handling on the client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentStep, Experiment, Run
from app.db.session import AsyncSessionLocal, get_session
from app.events.bus import bus, experiment_channel, run_channel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["events"])

# A model call against stealth/ox-alpha was MEASURED at 7-8 minutes, so long
# silences are normal, not a hung stream. The keepalive comment is what stops an
# intermediary from tearing the connection down during one.
KEEPALIVE_SECONDS = 15

# Bound on how long we wait for Redis to confirm the subscription before serving
# history anyway. A dead Redis must degrade to "history plus keepalives", never
# to a stream that never opens.
SUBSCRIBE_READY_TIMEOUT_S = 5.0

TERMINAL_RUN_STATUSES = ("completed", "failed", "cancelled")
TERMINAL_EXPERIMENT_STATUSES = ("completed", "failed")


def format_sse(data: str, event: str | None = None) -> str:
    # Newlines inside the payload would split the frame; JSON-escape them.
    safe = data.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {safe}\n\n"


def step_to_event(step, arm: str) -> dict:
    return {
        "run_id": str(step.run_id),
        "arm": arm,
        "seq": step.seq,
        "node": step.node,
        "kind": step.kind,
        "title": step.title,
        "detail": step.detail,
        "payload": step.payload or {},
        "ts": step.created_at.isoformat() if step.created_at else "",
    }


async def replay_steps(session: AsyncSession, runs: list[Run]) -> list[dict]:
    if not runs:
        return []
    arms = {r.id: r.arm for r in runs}
    rows = (
        await session.execute(
            select(AgentStep)
            .where(AgentStep.run_id.in_(list(arms)))
            .order_by(AgentStep.created_at, AgentStep.seq)
        )
    ).scalars().all()
    return [step_to_event(s, arms.get(s.run_id, "base")) for s in rows]


def _event_key(payload: str) -> tuple[str, int] | None:
    """(run_id, seq) identity of a live frame, or None if it is not an event."""
    try:
        parsed = json.loads(payload)
        return (str(parsed["run_id"]), int(parsed["seq"]))
    except (ValueError, TypeError, KeyError):
        return None


async def _stream(
    channel: str,
    load_history: Callable[[], Awaitable[list[dict]]],
    done_check: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    """Subscribe first, then replay, then stream — de-duplicating the overlap.

    DEVIATION FROM PLAN: the plan replayed from Postgres and only then
    subscribed to Redis, which loses any event published in between. Since the
    emitter persists before it publishes, subscribing first and discarding live
    frames already present in the replay closes that window without the client
    needing any de-duplication of its own.
    """
    queue: asyncio.Queue[str] = asyncio.Queue()
    ready = asyncio.Event()

    async def pump() -> None:
        try:
            async for message in bus.subscribe(channel, ready=ready):
                await queue.put(message)
        except Exception as exc:
            logger.warning("event subscription ended for %s: %s", channel, exc)
        finally:
            # Unblock the wait below even if the subscription never came up.
            ready.set()

    task = asyncio.create_task(pump())
    try:
        try:
            await asyncio.wait_for(ready.wait(), timeout=SUBSCRIBE_READY_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning("redis subscription for %s not ready; replaying anyway", channel)

        try:
            history = await load_history()
        except Exception as exc:
            logger.exception("history replay failed for %s", channel)
            history = []
            yield format_sse(json.dumps({"kind": "error", "detail": f"replay failed: {exc}"}))

        seen: set[tuple[str, int]] = set()
        for event in history:
            key = (str(event.get("run_id")), int(event.get("seq", -1)))
            seen.add(key)
            yield format_sse(json.dumps(event))

        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                key = _event_key(message)
                if key is not None and key in seen:
                    continue  # already delivered by the replay
                if key is not None:
                    seen.add(key)
                yield format_sse(message)
            except asyncio.TimeoutError:
                if await done_check():
                    yield format_sse(json.dumps({"kind": "stream_end"}), event="end")
                    return
                yield ": keepalive\n\n"
    finally:
        task.cancel()


def _sse_response(generator: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # keeps proxies from swallowing the stream
        },
    )


@router.get("/runs/{run_id}/events")
async def run_events(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    # The request-scoped session is not safe to touch from inside the streaming
    # generator — it is torn down once the endpoint returns — so history is read
    # on a session of the stream's own.
    async def load_history() -> list[dict]:
        async with AsyncSessionLocal() as s:
            fresh = await s.get(Run, run_id)
            return await replay_steps(s, [fresh] if fresh is not None else [])

    async def finished() -> bool:
        async with AsyncSessionLocal() as s:
            fresh = await s.get(Run, run_id)
            return fresh is not None and fresh.status in TERMINAL_RUN_STATUSES

    return _sse_response(_stream(run_channel(run_id), load_history, finished))


@router.get("/experiments/{experiment_id}/events")
async def experiment_events(
    experiment_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    experiment = await session.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")

    async def load_history() -> list[dict]:
        async with AsyncSessionLocal() as s:
            runs = (
                await s.execute(select(Run).where(Run.experiment_id == experiment_id))
            ).scalars().all()
            return await replay_steps(s, list(runs))

    async def finished() -> bool:
        async with AsyncSessionLocal() as s:
            fresh = await s.get(Experiment, experiment_id)
            return fresh is not None and fresh.status in TERMINAL_EXPERIMENT_STATUSES

    return _sse_response(_stream(experiment_channel(experiment_id), load_history, finished))
