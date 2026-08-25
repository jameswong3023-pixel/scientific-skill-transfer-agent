import base64
import shutil
from importlib.metadata import distributions

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from executor.runner import (
    ExecResult,
    PathEscapeError,
    resolve_in_workspace,
    run_python,
    workspace_path,
)

app = FastAPI(title="SSTA Sandbox Executor", version="0.1.0")


class ExecRequest(BaseModel):
    run_id: str
    code: str | None = None
    filename: str = "script.py"
    argv: list[str] = Field(default_factory=list)
    timeout_s: int = 600


class WriteRequest(BaseModel):
    run_id: str
    path: str
    content_b64: str


class ResetRequest(BaseModel):
    run_id: str


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/packages")
def packages() -> dict[str, list[dict[str, str]]]:
    """The sandbox has no network, so the agent cannot pip install.
    This is how it discovers what it already has."""
    out = []
    for dist in distributions():
        name = dist.metadata.get("Name")
        if name:
            out.append({"name": name, "version": dist.version or ""})
    out.sort(key=lambda d: d["name"].lower())
    return {"packages": out}


@app.post("/exec")
def execute(req: ExecRequest) -> dict:
    try:
        result: ExecResult = run_python(
            run_id=req.run_id,
            code=req.code,
            filename=req.filename,
            argv=req.argv,
            timeout_s=req.timeout_s,
        )
    except PathEscapeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.to_dict()


@app.post("/write")
def write(req: WriteRequest) -> dict:
    try:
        target = resolve_in_workspace(req.run_id, req.path)
    except PathEscapeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        data = base64.b64decode(req.content_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid base64") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"path": req.path, "bytes": len(data)}


@app.get("/files")
def files(run_id: str = Query(...)) -> dict:
    ws = workspace_path(run_id)
    out = []
    for p in sorted(ws.rglob("*")):
        if p.is_file():
            st = p.stat()
            out.append(
                {
                    "path": str(p.relative_to(ws)).replace("\\", "/"),
                    "bytes": st.st_size,
                    "modified": st.st_mtime,
                }
            )
    return {"files": out}


@app.get("/file")
def file(run_id: str = Query(...), path: str = Query(...)) -> Response:
    try:
        target = resolve_in_workspace(run_id, path)
    except PathEscapeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"not found: {path}")
    return Response(content=target.read_bytes(), media_type="application/octet-stream")


@app.post("/reset")
def reset(req: ResetRequest) -> dict:
    ws = workspace_path(req.run_id)
    if ws.exists():
        shutil.rmtree(ws, ignore_errors=True)
    workspace_path(req.run_id)
    return {"cleared": True}
