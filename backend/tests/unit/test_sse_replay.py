import json
import uuid

from app.api.routers import events as events_module
from app.api.routers.events import format_sse, step_to_event


class FakeStep:
    def __init__(self, seq, node, title, kind="node", payload=None, detail=""):
        self.run_id = uuid.uuid4()
        self.seq = seq
        self.node = node
        self.title = title
        self.kind = kind
        self.detail = detail
        self.payload = payload or {}
        from datetime import datetime, timezone

        self.created_at = datetime.now(timezone.utc)


def test_sse_framing_is_valid():
    frame = format_sse('{"a":1}')
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")


def test_sse_escapes_embedded_newlines():
    # A raw newline inside the payload would terminate the SSE frame early.
    frame = format_sse('{"stderr":"line1\nline2"}')
    body = [ln for ln in frame.split("\n") if ln.startswith("data: ")]
    assert len(body) == 1, "payload must be emitted as a single data line"


def test_persisted_step_maps_to_the_live_event_shape():
    step = FakeStep(3, "execute_code", "Running segment.py", kind="tool_call",
                    payload={"exit_code": 1})
    event = step_to_event(step, arm="skill")

    # Must be indistinguishable from what RunEventEmitter publishes, or the UI
    # would need two code paths for history and live.
    assert set(event) == {"run_id", "arm", "seq", "node", "kind", "title", "detail",
                          "payload", "ts"}
    assert event["seq"] == 3
    assert event["arm"] == "skill"
    assert event["payload"]["exit_code"] == 1


def test_event_is_json_serializable():
    event = step_to_event(FakeStep(1, "plan", "Planning"), arm="base")
    assert json.loads(json.dumps(event))["node"] == "plan"


def _evt(seq, run_id="r1", node="plan"):
    return {"run_id": run_id, "arm": "base", "seq": seq, "node": node, "kind": "node",
            "title": f"step {seq}", "detail": "", "payload": {}, "ts": ""}


class FakeBus:
    """Records when the subscription is established relative to the replay."""

    def __init__(self, live, ordering):
        self.live = live
        self.ordering = ordering

    async def subscribe(self, channel, ready=None):
        self.ordering.append("subscribe")
        if ready is not None:
            ready.set()
        for message in self.live:
            yield message


async def _collect(channel, live, history, monkeypatch):
    ordering: list[str] = []
    monkeypatch.setattr(events_module, "bus", FakeBus(live, ordering))
    # The loop only checks for completion after a silent keepalive interval;
    # shorten it so the test does not wait the production 15 seconds.
    monkeypatch.setattr(events_module, "KEEPALIVE_SECONDS", 0.05)

    async def load_history():
        ordering.append("replay")
        return history

    async def done():
        return True

    frames = [f async for f in events_module._stream(channel, load_history, done)]
    return frames, ordering


def _data_payloads(frames):
    out = []
    for frame in frames:
        for line in frame.split("\n"):
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


async def test_stream_subscribes_before_replaying_history(monkeypatch):
    # Subscribing second would drop anything published between the SELECT and
    # the SUBSCRIBE, which is exactly what persist-then-publish exists to avoid.
    _, ordering = await _collect("run:r1:events", [], [_evt(0)], monkeypatch)
    assert ordering[:2] == ["subscribe", "replay"]


async def test_stream_emits_history_then_live_events(monkeypatch):
    frames, _ = await _collect(
        "run:r1:events", [json.dumps(_evt(1))], [_evt(0)], monkeypatch
    )
    payloads = _data_payloads(frames)
    assert [p.get("seq") for p in payloads[:2]] == [0, 1]
    assert payloads[-1]["kind"] == "stream_end"


async def test_stream_does_not_deliver_an_event_twice(monkeypatch):
    # seq 0 is in the replay AND arrives live: the client must see it once.
    frames, _ = await _collect(
        "run:r1:events", [json.dumps(_evt(0)), json.dumps(_evt(1))], [_evt(0)], monkeypatch
    )
    seqs = [p["seq"] for p in _data_payloads(frames) if "seq" in p]
    assert seqs == [0, 1]


async def test_stream_serves_history_even_if_redis_never_subscribes(monkeypatch):
    class DeadBus:
        async def subscribe(self, channel, ready=None):
            raise ConnectionError("redis gone")
            yield ""  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(events_module, "bus", DeadBus())
    monkeypatch.setattr(events_module, "KEEPALIVE_SECONDS", 0.05)

    async def load_history():
        return [_evt(0)]

    async def done():
        return True

    frames = [f async for f in events_module._stream("run:r1:events", load_history, done)]
    seqs = [p["seq"] for p in _data_payloads(frames) if "seq" in p]
    assert seqs == [0], "a dead Redis must still yield the persisted timeline"


async def test_stream_keeps_the_connection_alive_while_the_run_is_unfinished(monkeypatch):
    monkeypatch.setattr(events_module, "bus", FakeBus([], []))
    monkeypatch.setattr(events_module, "KEEPALIVE_SECONDS", 0.02)
    calls = {"n": 0}

    async def load_history():
        return []

    async def done():
        calls["n"] += 1
        return calls["n"] > 2  # unfinished twice, then terminal

    frames = []
    async for frame in events_module._stream("run:r1:events", load_history, done):
        frames.append(frame)
    assert frames.count(": keepalive\n\n") == 2
