from app.db.base import Base
from app.db.models import AgentStep, Artifact, Experiment, Run, RunArm, RunStatus


def test_tables_registered():
    for t in (
        "experiments", "runs", "agent_steps", "tool_calls",
        "artifacts", "metrics", "conversations", "messages",
    ):
        assert t in Base.metadata.tables, f"missing {t}"


def test_run_arm_values():
    assert RunArm.BASE == "base"
    assert RunArm.SKILL == "skill"


def test_experiment_pins_an_immutable_skill_version_not_a_skill():
    cols = set(Base.metadata.tables["experiments"].columns.keys())
    assert "skill_version_id" in cols, "must pin a version for reproducibility"
    assert "skill_id" not in cols


def test_one_run_per_arm_per_experiment():
    constraints = {c.name for c in Base.metadata.tables["runs"].constraints}
    assert "uq_run_experiment_arm" in constraints


def test_agent_step_has_ordering_key():
    cols = Base.metadata.tables["agent_steps"].columns
    assert "seq" in cols and "run_id" in cols


def test_artifact_points_at_storage_not_bytes():
    cols = set(Base.metadata.tables["artifacts"].columns.keys())
    assert "storage_key" in cols
    assert "content" not in cols


def test_defaults():
    r = Run(experiment_id=None, arm=RunArm.BASE)
    assert r.status == RunStatus.PENDING
    s = AgentStep(run_id=None, seq=0, node="plan", kind="node", title="t")
    assert s.payload == {} or s.payload is None
    a = Artifact(run_id=None, kind="output", path="x.nii.gz", storage_key="k")
    assert a.kind == "output"


def test_experiment_is_importable_and_named():
    assert Experiment.__tablename__ == "experiments"
