"""The agent's tool surface.

This list is IDENTICAL for both experimental arms. Adding an arm-specific tool
would make the two agents differ in capability, not just in knowledge, and
would invalidate the A/B comparison — which is why the extracted skill is
delivered through the system prompt instead of a `get_skill` tool.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List every file currently in your workspace, with sizes.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_image",
            "description": (
                "Inspect a scientific image without loading it yourself. Returns shape, "
                "dtype, voxel spacing, intensity range, percentiles, and whether the data "
                "looks like a label map. Works for NIfTI, DICOM, TIFF, PNG/JPEG and .npy."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative path"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_text",
            "description": "Read a text file from the workspace (e.g. your own script, or a log).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_chars": {"type": "integer", "description": "Default 20000"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a text file into the workspace without executing it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "Write a Python script to the workspace and execute it. Returns exit code, "
                "stdout, stderr and any files created. A non-zero exit is normal — read the "
                "traceback and fix your code. The sandbox has NO network access."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Full script source"},
                    "filename": {
                        "type": "string",
                        "description": "Where to save it, e.g. 'segment.py'. Default 'script.py'.",
                    },
                    "timeout_s": {"type": "integer", "description": "Default 600"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_packages",
            "description": (
                "List the Python packages installed in the sandbox. You cannot install "
                "anything — the sandbox has no network — so check here before importing."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_artifact",
            "description": (
                "Mark a file you produced as a final deliverable so it is preserved, "
                "shown in the UI, and included in the downloadable results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative path"},
                    "kind": {
                        "type": "string",
                        "enum": ["output", "figure", "report", "code", "log"],
                    },
                    "description": {"type": "string"},
                },
                "required": ["path", "kind"],
            },
        },
    },
]

TOOL_NAMES = frozenset(s["function"]["name"] for s in TOOL_SCHEMAS)


@dataclass
class ToolContext:
    run_id: str
    sandbox: Any
    emit: Callable[..., Awaitable[None]]
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    executions: int = 0
    failed_executions: int = 0


async def _list_files(ctx: ToolContext, args: dict) -> str:
    files = await ctx.sandbox.list_files(ctx.run_id)
    if not files:
        return "Workspace is empty."
    lines = [f"  {f['path']}  ({f['bytes']:,} bytes)" for f in files]
    return f"{len(files)} file(s):\n" + "\n".join(lines)


async def _inspect_image(ctx: ToolContext, args: dict) -> str:
    import json

    from app.imaging.loaders import UnreadableImageError, describe

    path = args["path"]
    data = await ctx.sandbox.read_file(ctx.run_id, path)
    suffix = "".join(Path(path).suffixes[-2:]) or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
        fh.write(data)
        tmp = fh.name
    try:
        info = describe(tmp, Path(path).name)
    except UnreadableImageError as exc:
        return f"Could not read {path} as an image: {exc}"
    finally:
        Path(tmp).unlink(missing_ok=True)

    await ctx.emit(
        "inspect_data",
        f"Inspected {path}: {info.get('shape')} {info.get('dtype')}",
        info,
        kind="tool_call",
    )
    # DEVIATION FROM PLAN: the plan returned `json.dumps(info, indent=2)` alone.
    # Indented JSON explodes `"shape": [4, 5, 6]` onto one element per line, so the
    # single most important fact — the array shape — never appears as a readable
    # tuple anywhere in the observation. The compact headline restores it for the
    # model (and satisfies the plan's own shape/dtype assertion); the full JSON
    # body follows unchanged.
    headline = (
        f"{path}: shape={info.get('shape')} dtype={info.get('dtype')} "
        f"spacing={info.get('spacing')} value_range={info.get('value_range')}"
    )
    return headline + "\n" + json.dumps(info, indent=2)


async def _read_text(ctx: ToolContext, args: dict) -> str:
    limit = int(args.get("max_chars", 20000))
    data = await ctx.sandbox.read_file(ctx.run_id, args["path"])
    text = data.decode("utf-8", errors="replace")
    if len(text) > limit:
        return text[:limit] + f"\n...[truncated, {len(text) - limit} more chars]"
    return text


async def _write_file(ctx: ToolContext, args: dict) -> str:
    path, content = args["path"], args["content"]
    await ctx.sandbox.write_file(ctx.run_id, path, content.encode("utf-8"))
    return f"Wrote {path} ({len(content)} chars)."


async def _run_python(ctx: ToolContext, args: dict) -> str:
    filename = args.get("filename") or "script.py"
    code = args["code"]
    await ctx.emit("execute_code", f"Running {filename}", {"filename": filename}, kind="tool_call")

    result = await ctx.sandbox.execute(
        ctx.run_id, code=code, filename=filename, timeout_s=args.get("timeout_s")
    )
    ctx.executions += 1
    if not result.ok:
        ctx.failed_executions += 1

    summary = (
        f"{filename} exited {result.exit_code} in {result.duration_ms}ms"
        + (" (TIMEOUT)" if result.timed_out else "")
    )
    await ctx.emit(
        "execute_code",
        summary,
        {
            "filename": filename,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "timed_out": result.timed_out,
            "files_created": result.files_created,
            "stderr_tail": result.stderr[-1200:],
        },
        kind="tool_result",
    )
    return result.as_observation()


async def _list_packages(ctx: ToolContext, args: dict) -> str:
    packages = await ctx.sandbox.packages()
    if not packages:
        return "Could not list packages."
    return "Installed packages:\n" + ", ".join(
        f"{p['name']}=={p['version']}" for p in packages
    )


async def _save_artifact(ctx: ToolContext, args: dict) -> str:
    entry = {
        "path": args["path"],
        "kind": args.get("kind", "output"),
        "description": args.get("description", ""),
    }
    ctx.artifacts.append(entry)
    await ctx.emit("finalize", f"Saved artifact {entry['path']}", entry, kind="artifact")
    return f"Recorded {entry['path']} as a {entry['kind']} artifact."


_HANDLERS: dict[str, Callable[[ToolContext, dict], Awaitable[str]]] = {
    "list_files": _list_files,
    "inspect_image": _inspect_image,
    "read_text": _read_text,
    "write_file": _write_file,
    "run_python": _run_python,
    "list_packages": _list_packages,
    "save_artifact": _save_artifact,
}


async def dispatch_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> str:
    """Always returns a string observation. Never raises — an exception here
    would end the run, whereas a described error lets the agent adapt."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return (
            f"Unknown tool '{name}'. Available tools: {', '.join(sorted(TOOL_NAMES))}. "
            f"Note there is no package-installation tool: the sandbox has no network."
        )
    try:
        return await handler(ctx, args)
    except KeyError as exc:
        return f"Tool '{name}' error: missing required argument {exc}"
    except Exception as exc:
        logger.exception("tool %s failed", name)
        return f"Tool '{name}' raised an error: {type(exc).__name__}: {exc}"
