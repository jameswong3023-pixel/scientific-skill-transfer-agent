import json

from app.events.bus import RunEvent, RunEventEmitter, experiment_channel, run_channel


class FakeBus:
    def __init__(self):
        self.published: list[tuple[RunEvent, str | None]] = []

    async def publish(self, event, experiment_id=None):
        self.published.append((event, experiment_id))


class FakeSession:
    def __init__(self):
        self.added: list = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def flush(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def test_channels_are_namespaced():
    assert run_channel("r1") == "run:r1:events"
    assert experiment_channel("e1") == "experiment:e1:events"


def test_event_serializes_to_json():
    e = RunEvent(run_id="r", arm="base", seq=1, node="plan", kind="node",
                 title="Planning", detail="", payload={"a": 1}, ts="2026-01-01T00:00:00Z")
    parsed = json.loads(e.to_json())
    assert parsed["node"] == "plan"
    assert parsed["arm"] == "base"
    assert parsed["payload"] == {"a": 1}


async def test_emitter_assigns_monotonic_sequence():
    bus = FakeBus()
    session = FakeSession()
    emit = RunEventEmitter("r1", "skill", lambda: session, bus, experiment_id="e1")

    await emit("plan", "Planning")
    await emit("inspect_data", "Inspecting")
    await emit("write_code", "Writing")

    assert [e.seq for e, _ in bus.published] == [0, 1, 2]


async def test_emitter_persists_a_step_for_every_event():
    bus = FakeBus()
    session = FakeSession()
    emit = RunEventEmitter("r1", "base", lambda: session, bus)

    await emit("plan", "Planning", {"x": 1})
    await emit("execute_code", "Running script.py", {"exit_code": 1}, kind="tool_call")

    assert len(session.added) == 2, "every event must be replayable from the database"
    assert session.added[1].node == "execute_code"
    assert session.added[1].kind == "tool_call"
    assert session.added[1].payload == {"exit_code": 1}


async def test_emitter_publishes_to_both_run_and_experiment_channels():
    bus = FakeBus()
    emit = RunEventEmitter("r1", "base", lambda: FakeSession(), bus, experiment_id="e9")
    await emit("plan", "Planning")
    _, experiment_id = bus.published[0]
    assert experiment_id == "e9"


async def test_emitter_carries_the_arm_so_the_ui_can_split_streams():
    bus = FakeBus()
    emit = RunEventEmitter("r1", "skill", lambda: FakeSession(), bus)
    await emit("plan", "Planning")
    assert bus.published[0][0].arm == "skill"


async def test_publish_failure_does_not_kill_the_run():
    class BrokenBus:
        async def publish(self, event, experiment_id=None):
            raise ConnectionError("redis gone")

    emit = RunEventEmitter("r1", "base", lambda: FakeSession(), BrokenBus())
    await emit("plan", "Planning")  # must not raise — progress is best-effort, work is not
