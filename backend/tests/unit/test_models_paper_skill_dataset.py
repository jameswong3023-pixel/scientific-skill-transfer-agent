from app.db.base import Base
from app.db.models import (
    Dataset,
    DatasetFile,
    DatasetFileRole,
    Paper,
    PaperStatus,
    Skill,
    SkillVersion,
    Workspace,
)


def test_all_tables_registered():
    for t in (
        "users", "workspaces", "papers", "paper_pages",
        "skills", "skill_versions", "datasets", "dataset_files",
    ):
        assert t in Base.metadata.tables, f"missing table {t}"


def test_paper_status_lifecycle_values():
    assert PaperStatus.UPLOADED == "uploaded"
    assert PaperStatus.EXTRACTED == "extracted"
    assert PaperStatus.FAILED == "failed"


def test_ground_truth_role_value_is_stable():
    # Ground-truth filtering across the whole codebase keys off this literal.
    assert DatasetFileRole.GROUND_TRUTH == "ground_truth"
    assert DatasetFileRole.INPUT == "input"


def test_paper_never_stores_bytes_only_a_key():
    cols = set(Base.metadata.tables["papers"].columns.keys())
    assert "storage_key" in cols
    assert "content" not in cols and "data" not in cols


def test_skill_version_is_versioned_and_pinned_to_payload():
    cols = Base.metadata.tables["skill_versions"].columns
    assert "version" in cols and "payload" in cols and "skill_id" in cols


def test_defaults_applied_on_construction():
    p = Paper(workspace_id=None, filename="a.pdf", storage_key="k", sha256="s")
    assert p.status == PaperStatus.UPLOADED
    d = DatasetFile(dataset_id=None, filename="a.nii.gz", storage_key="k", sha256="s", bytes=1)
    assert d.role == DatasetFileRole.INPUT


def test_workspace_and_dataset_are_importable():
    assert Workspace.__tablename__ == "workspaces"
    assert Dataset.__tablename__ == "datasets"
    assert Skill.__tablename__ == "skills"
    assert SkillVersion.__tablename__ == "skill_versions"
