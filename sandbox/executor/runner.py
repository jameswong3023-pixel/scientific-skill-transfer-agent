"""Executes untrusted, model-generated Python.

Isolation posture (defence in depth — no single control is relied upon):
  * process    : separate container, uid 1000, never root
  * network    : container sits on an `internal: true` compose network
  * filesystem : cwd pinned to /work/{run_id}; every path resolved and asserted inside it
  * memory     : RLIMIT_AS
  * cpu        : RLIMIT_CPU (soft) + wall-clock SIGKILL (hard)
  * fds/procs  : RLIMIT_NOFILE, RLIMIT_NPROC
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# `resource` and `preexec_fn` are POSIX-only. The sandbox always ships as a
# Linux container, so the rlimit controls above are always active in the
# deployed system; this guard exists purely so the suite is runnable on a
# developer's Windows host. The wall-clock SIGKILL and the path containment
# checks -- the two controls that do not depend on the OS -- stay active
# everywhere, so the tests still exercise them.
if os.name == "posix":  # pragma: no cover - platform branch
    import resource
else:  # pragma: no cover - platform branch
    resource = None  # type: ignore[assignment]


class PathEscapeError(ValueError):
    """Raised when a requested path would leave the run workspace."""


def _work_root() -> Path:
    return Path(os.getenv("SANDBOX_WORK_ROOT", "/work")).resolve()


def workspace_path(run_id: str) -> Path:
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_")
    if not safe:
        raise PathEscapeError(f"invalid run id: {run_id!r}")
    p = _work_root() / safe
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve_in_workspace(run_id: str, rel: str) -> Path:
    if rel.startswith(("/", "\\", "~")) or (len(rel) > 1 and rel[1] == ":"):
        raise PathEscapeError(f"absolute path not allowed: {rel}")
    ws = workspace_path(run_id)
    candidate = (ws / rel).resolve()
    if not str(candidate).startswith(str(ws.resolve())):
        raise PathEscapeError(f"path escapes workspace: {rel}")
    return candidate


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    files_created: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "files_created": self.files_created,
        }


def _snapshot(ws: Path) -> set[str]:
    return {
        str(p.relative_to(ws)).replace(os.sep, "/") for p in ws.rglob("*") if p.is_file()
    }


def _apply_limits(memory_mb: int, cpu_seconds: int):
    if resource is None:  # pragma: no cover - platform branch
        return None

    def _preexec() -> None:
        mem = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5))
        resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
        resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.setsid()

    return _preexec


MAX_CAPTURE = 200_000  # chars; agent context is finite and stack traces can be enormous


def _truncate(s: str) -> str:
    if len(s) <= MAX_CAPTURE:
        return s
    half = MAX_CAPTURE // 2
    return f"{s[:half]}\n\n...[{len(s) - MAX_CAPTURE} chars truncated]...\n\n{s[-half:]}"


def _child_env() -> dict[str, str]:
    """A deliberately minimal environment: the child inherits nothing from the
    executor process, so no stray configuration or credential can reach agent
    code even if one were ever introduced into this container."""
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "MPLBACKEND": "Agg",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
    }
    if os.name == "nt":  # pragma: no cover - platform branch
        # CPython on Windows cannot even start without SystemRoot (it needs
        # the OS CSPRNG to seed hash randomisation), and the POSIX PATH above
        # is meaningless there. Dev-host affordance only; the container path
        # is unchanged.
        env["PATH"] = os.environ.get("PATH", "")
        for key in ("SYSTEMROOT", "SystemRoot", "COMSPEC", "PATHEXT", "TEMP", "TMP"):
            if key in os.environ:
                env[key] = os.environ[key]
    return env


def run_python(
    run_id: str,
    code: str | None = None,
    filename: str = "script.py",
    argv: list[str] | None = None,
    timeout_s: int = 600,
    memory_mb: int | None = None,
) -> ExecResult:
    """Run Python in the run's workspace. Never raises on user-code failure —
    a failing script is a normal observation the agent must be able to react to."""
    ws = workspace_path(run_id)
    max_timeout = int(os.getenv("SANDBOX_MAX_TIMEOUT_S", "900"))
    timeout_s = max(1, min(int(timeout_s), max_timeout))
    memory_mb = memory_mb or int(os.getenv("SANDBOX_MEMORY_MB", "3072"))

    target = resolve_in_workspace(run_id, filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    if code is not None:
        target.write_text(code, encoding="utf-8")
    if not target.exists():
        return ExecResult(
            exit_code=2, stdout="", stderr=f"file not found: {filename}", duration_ms=0
        )

    before = _snapshot(ws)
    env = _child_env()

    start = time.perf_counter()
    timed_out = False
    try:
        proc = subprocess.run(
            [sys.executable, str(target), *(argv or [])],
            cwd=str(ws),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            preexec_fn=_apply_limits(memory_mb, timeout_s),
            check=False,
        )
        exit_code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = (
            (exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or ""))
            + f"\n[sandbox] killed after {timeout_s}s wall-clock limit"
        )
    except MemoryError:
        timed_out = False
        exit_code = 137
        stdout, stderr = "", f"[sandbox] exceeded {memory_mb}MB memory limit"

    duration_ms = int((time.perf_counter() - start) * 1000)
    created = sorted(_snapshot(ws) - before)

    return ExecResult(
        exit_code=exit_code,
        stdout=_truncate(stdout),
        stderr=_truncate(stderr),
        duration_ms=duration_ms,
        timed_out=timed_out,
        files_created=created,
    )
