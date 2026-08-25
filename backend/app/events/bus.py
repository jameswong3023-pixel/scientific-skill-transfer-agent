"""Progress events.

Every event is written to `agent_steps` before it is published. That ordering is
deliberate: the database is the source of truth and pub/sub is a live overlay,
so a client that connects late (or reconnects after a drop) can replay the full
history and then attach to the stream without a gap.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from app.db.models import AgentStep

logger = logging.getLogger(__name__)


def run_channel(run_id: str | uuid.UUID) -> str:
    return f"run:{run_id}:events"


def experiment_channel(experiment_id: str | uuid.UUID) -> str:
    return f"experiment:{experiment_id}:events"


def _coerce_run_id(value: str) -> Any:
    """Return a `uuid.UUID` when the id is one, otherwise the raw string.

    DEVIATION FROM PLAN (plan wrote `uuid.UUID(self.run_id)` unconditionally):
    a non-UUID run id made `uuid.UUID()` raise *inside* the persistence
    try/except, so the AgentStep was never constructed and the event was
    silently dropped — the exact failure the "persist first" ordering exists to
    prevent. Real run ids are always UUIDs; passing anything else straight
    through lets SQLAlchemy fail loudly at flush instead of losing the timeline.
    """
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return value


@dataclass
class RunEvent:
    run_id: str
    arm: str
    seq: int
    node: str
    kind: str
    title: str
    detail: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class EventBus:
    def __init__(self, url: str | None = None) -> None:
        self._url = url or settings.redis_url
        self._redis: aioredis.Redis | None = None

    async def _client(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self._url, decode_responses=True)
        return self._redis

    async def publish(self, event: RunEvent, experiment_id: str | None = None) -> None:
        client = await self._client()
        body = event.to_json()
        await client.publish(run_channel(event.run_id), body)
        if experiment_id:
            await client.publish(experiment_channel(experiment_id), body)

    async def subscribe(
        self, channel: str, ready: asyncio.Event | None = None
    ) -> AsyncIterator[str]:
        """Yield published payloads for `channel`.

        `ready` is set once the SUBSCRIBE has actually landed. The SSE endpoint
        waits on it before reading history from Postgres, so there is no window
        in which an event is persisted-and-published but neither replayed nor
        streamed. Without it, "replay then subscribe" silently drops anything
        emitted between the SELECT and the SUBSCRIBE.
        """
        client = await self._client()
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        if ready is not None:
            ready.set()
        try:
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    yield message["data"]
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None


bus = EventBus()


class RunEventEmitter:
    """Callable with the `Emitter` signature the graphs expect: (node, title, payload)."""

    def __init__(
        self,
        run_id: str | uuid.UUID,
        arm: str,
        session_factory: Callable[[], Any],
        event_bus: Any = None,
        experiment_id: str | uuid.UUID | None = None,
    ) -> None:
        self.run_id = str(run_id)
        self.arm = arm
        self.session_factory = session_factory
        self.bus = event_bus if event_bus is not None else bus
        self.experiment_id = str(experiment_id) if experiment_id else None
        self._seq = 0

    async def __call__(
        self,
        node: str,
        title: str,
        payload: dict[str, Any] | None = None,
        kind: str = "node",
        detail: str = "",
    ) -> None:
        event = RunEvent(
            run_id=self.run_id,
            arm=self.arm,
            seq=self._seq,
            node=node,
            kind=kind,
            title=title[:300],
            detail=detail,
            payload=payload or {},
            ts=datetime.now(timezone.utc).isoformat(),
        )
        self._seq += 1

        # Persist first: the timeline must survive a Redis outage.
        try:
            session = self.session_factory()
            async with session as s:
                s.add(
                    AgentStep(
                        run_id=_coerce_run_id(self.run_id),
                        seq=event.seq,
                        node=event.node,
                        kind=event.kind,
                        title=event.title,
                        detail=event.detail,
                        payload=event.payload,
                    )
                )
                await s.commit()
        except Exception as exc:
            logger.error("failed to persist step %s/%d: %s", self.run_id, event.seq, exc)

        # Publishing is best-effort. A dead Redis must never fail the analysis.
        try:
            await self.bus.publish(event, self.experiment_id)
        except Exception as exc:
            logger.warning("failed to publish event %s/%d: %s", self.run_id, event.seq, exc)
