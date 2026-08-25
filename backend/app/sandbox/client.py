import base64
import logging

import httpx
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)


class ExecutionResult(BaseModel):
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False
    files_created: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def as_observation(self) -> str:
        """Rendered back into the agent transcript. Compact on success,
        detailed on failure — failure is what the model needs to act on."""
        if self.ok:
            head = f"Exit 0 in {self.duration_ms}ms."
            files = f" Created: {', '.join(self.files_created)}." if self.files_created else ""
            return f"{head}{files}\nSTDOUT:\n{self.stdout[:8000]}"
        reason = "TIMEOUT" if self.timed_out else f"exit code {self.exit_code}"
        return (
            f"EXECUTION FAILED ({reason}) after {self.duration_ms}ms.\n"
            f"STDOUT:\n{self.stdout[:4000]}\n\nSTDERR:\n{self.stderr[:12000]}"
        )


class SandboxClient:
    def __init__(
        self,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        default_timeout_s: int | None = None,
    ) -> None:
        self.base_url = base_url or settings.sandbox_url
        self.default_timeout_s = default_timeout_s or settings.sandbox_timeout_s
        # Always outlive the sandbox's own limit so we observe its verdict
        # rather than inventing our own.
        self.http_timeout = self.default_timeout_s + 60
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url, timeout=self.http_timeout, transport=self._transport
        )

    async def health(self) -> bool:
        try:
            async with self._client() as c:
                return (await c.get("/healthz")).status_code == 200
        except Exception:
            return False

    async def packages(self) -> list[dict[str, str]]:
        try:
            async with self._client() as c:
                return (await c.get("/packages")).json()["packages"]
        except Exception as exc:
            logger.warning("package listing failed: %s", exc)
            return []

    async def execute(
        self,
        run_id: str,
        code: str | None = None,
        filename: str = "script.py",
        argv: list[str] | None = None,
        timeout_s: int | None = None,
    ) -> ExecutionResult:
        payload = {
            "run_id": str(run_id),
            "code": code,
            "filename": filename,
            "argv": argv or [],
            "timeout_s": timeout_s or self.default_timeout_s,
        }
        try:
            async with self._client() as c:
                resp = await c.post("/exec", json=payload)
                resp.raise_for_status()
                return ExecutionResult(**resp.json())
        except Exception as exc:
            # The agent must always get an observation it can reason about.
            logger.error("sandbox execution transport failure: %s", exc)
            return ExecutionResult(
                exit_code=-1,
                stderr=f"Sandbox unavailable: {type(exc).__name__}: {exc}",
                duration_ms=0,
            )

    async def write_file(self, run_id: str, path: str, data: bytes) -> None:
        async with self._client() as c:
            resp = await c.post(
                "/write",
                json={
                    "run_id": str(run_id),
                    "path": path,
                    "content_b64": base64.b64encode(data).decode(),
                },
            )
            resp.raise_for_status()

    async def list_files(self, run_id: str) -> list[dict]:
        async with self._client() as c:
            resp = await c.get("/files", params={"run_id": str(run_id)})
            resp.raise_for_status()
            return resp.json()["files"]

    async def read_file(self, run_id: str, path: str) -> bytes:
        async with self._client() as c:
            resp = await c.get("/file", params={"run_id": str(run_id), "path": path})
            resp.raise_for_status()
            return resp.content

    async def reset(self, run_id: str) -> None:
        async with self._client() as c:
            await c.post("/reset", json={"run_id": str(run_id)})


sandbox_client = SandboxClient()
