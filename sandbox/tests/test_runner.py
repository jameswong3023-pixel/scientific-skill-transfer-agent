import pytest

from executor.runner import (
    ExecResult,
    PathEscapeError,
    resolve_in_workspace,
    run_python,
    workspace_path,
)


def test_workspace_is_created_and_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_WORK_ROOT", str(tmp_path))
    p = workspace_path("run-1")
    assert p.exists() and p.name == "run-1"


@pytest.mark.parametrize("bad", ["../escape.py", "a/../../b.py", "/etc/passwd", "~/x.py"])
def test_traversal_is_rejected(tmp_path, monkeypatch, bad):
    monkeypatch.setenv("SANDBOX_WORK_ROOT", str(tmp_path))
    with pytest.raises(PathEscapeError):
        resolve_in_workspace("run-1", bad)


def test_normal_paths_resolve(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_WORK_ROOT", str(tmp_path))
    p = resolve_in_workspace("run-1", "outputs/seg.nii.gz")
    assert str(p).endswith("run-1/outputs/seg.nii.gz".replace("/", __import__("os").sep))


def test_successful_execution_captures_stdout(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_WORK_ROOT", str(tmp_path))
    r = run_python("run-1", code="print('hello sandbox')", timeout_s=30)
    assert isinstance(r, ExecResult)
    assert r.exit_code == 0
    assert "hello sandbox" in r.stdout
    assert r.timed_out is False
    assert r.duration_ms >= 0


def test_failure_is_returned_not_raised(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_WORK_ROOT", str(tmp_path))
    r = run_python("run-1", code="raise ValueError('boom')", timeout_s=30)
    assert r.exit_code != 0
    assert "ValueError: boom" in r.stderr
    # Critical: the agent loop depends on failures being observations, not exceptions.


def test_timeout_kills_and_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_WORK_ROOT", str(tmp_path))
    r = run_python("run-1", code="import time\nwhile True: time.sleep(1)", timeout_s=2)
    assert r.timed_out is True
    assert r.exit_code != 0


def test_new_files_are_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_WORK_ROOT", str(tmp_path))
    code = "open('result.txt','w').write('x')"
    r = run_python("run-2", code=code, timeout_s=30)
    assert r.exit_code == 0
    assert "result.txt" in r.files_created


def test_runs_are_isolated_from_each_other(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_WORK_ROOT", str(tmp_path))
    run_python("run-a", code="open('a.txt','w').write('a')", timeout_s=30)
    r = run_python("run-b", code="import os; print(os.listdir('.'))", timeout_s=30)
    assert "a.txt" not in r.stdout
