"""Read-only tools for the conversational agent.

The chat surface deliberately cannot execute code or write files. It answers
questions about work that already happened by reading the same rows the UI
renders, which keeps answers grounded and keeps the attack surface small.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

CONVERSATION_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_experiment_summary",
            "description": "The task, status, configuration, and each arm's final summary.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_skill",
            "description": (
                "The skill extracted from the paper, including which fields were quoted "
                "from the paper and which were inferred."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_artifacts",
            "description": "Files produced by a run.",
            "parameters": {
                "type": "object",
                "properties": {"arm": {"type": "string", "enum": ["base", "skill"]}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_artifact_text",
            "description": "Read a text artifact (a script, measurements.json, a summary).",
            "parameters": {
                "type": "object",
                "properties": {
                    "arm": {"type": "string", "enum": ["base", "skill"]},
                    "path": {"type": "string"},
                },
                "required": ["arm", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_run_steps",
            "description": (
                "The execution timeline for one arm: every node, tool call, failure and "
                "recovery, in order. Use this to explain what the agent did or why it failed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "arm": {"type": "string", "enum": ["base", "skill"]},
                    "only_failures": {"type": "boolean"},
                },
                "required": ["arm"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_metrics",
            "description": (
                "Quantitative results for both arms: Dice, IoU, volumes, and system metrics."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


@dataclass
class ConversationContext:
    experiment_id: uuid.UUID
    session_factory: Any


async def dispatch_conversation_tool(ctx: ConversationContext, name: str, args: dict) -> str:
    from app.db.models import AgentStep, Artifact, Experiment, Metric, Run, SkillVersion
    from app.storage.s3 import store

    args = args or {}

    async with ctx.session_factory() as session:
        experiment = await session.get(Experiment, ctx.experiment_id)
        if experiment is None:
            return "Experiment not found."

        runs = (
            await session.execute(select(Run).where(Run.experiment_id == ctx.experiment_id))
        ).scalars().all()
        by_arm = {r.arm: r for r in runs}

        if name == "get_experiment_summary":
            return json.dumps(
                {
                    "task": experiment.task_prompt,
                    "status": experiment.status,
                    "config": experiment.config,
                    "runs": {
                        r.arm: {
                            "status": r.status,
                            "error": r.error,
                            "summary": (r.totals or {}).get("summary", ""),
                            "iterations": (r.totals or {}).get("iterations"),
                            "executions": (r.totals or {}).get("executions"),
                            "failed_executions": (r.totals or {}).get("failed_executions"),
                        }
                        for r in runs
                    },
                },
                indent=2, default=str,
            )

        if name == "get_skill":
            if not experiment.skill_version_id:
                return "This experiment had no skill (both arms would be identical)."
            version = await session.get(SkillVersion, experiment.skill_version_id)
            if version is None:
                return "Skill version not found."
            return json.dumps(
                {"version": version.version, "validation": version.validation,
                 "skill": version.payload},
                indent=2, default=str,
            )

        if name == "list_artifacts":
            arm = args.get("arm")
            target = [by_arm[arm]] if arm in by_arm else runs
            rows = (
                await session.execute(
                    select(Artifact).where(Artifact.run_id.in_([r.id for r in target] or [None]))
                )
            ).scalars().all()
            return json.dumps(
                [{"arm": next((r.arm for r in target if r.id == a.run_id), "?"),
                  "path": a.path, "kind": a.kind, "bytes": a.bytes} for a in rows],
                indent=2,
            )

        if name == "read_artifact_text":
            run = by_arm.get(args.get("arm", ""))
            if run is None:
                return f"No run for arm {args.get('arm')!r}."
            path = args.get("path")
            if not path:
                return "read_artifact_text needs a `path`."
            artifact = (
                await session.execute(
                    select(Artifact).where(Artifact.run_id == run.id, Artifact.path == path)
                )
            ).scalars().first()
            if artifact is None:
                return f"No artifact at {path} for the {args['arm']} arm."
            try:
                data = store.get_bytes(artifact.storage_key)
            except Exception as exc:
                return f"Could not read the artifact: {exc}"
            text = data.decode("utf-8", errors="replace")
            return text[:20000] + ("\n...[truncated]" if len(text) > 20000 else "")

        if name == "get_run_steps":
            run = by_arm.get(args.get("arm", ""))
            if run is None:
                return f"No run for arm {args.get('arm')!r}."
            steps = (
                await session.execute(
                    select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.seq)
                )
            ).scalars().all()
            if args.get("only_failures"):
                steps = [
                    s for s in steps
                    if s.kind == "error" or (s.payload or {}).get("exit_code") not in (None, 0)
                ]
            return json.dumps(
                [{"seq": s.seq, "node": s.node, "kind": s.kind, "title": s.title,
                  "payload": s.payload} for s in steps[:200]],
                indent=2, default=str,
            )

        if name == "get_metrics":
            rows = (
                await session.execute(
                    select(Metric).where(Metric.experiment_id == ctx.experiment_id)
                )
            ).scalars().all()
            arm_of = {r.id: r.arm for r in runs}
            return json.dumps(
                [{"arm": arm_of.get(m.run_id, "comparison"), "scope": m.scope,
                  "key": m.key, "value": m.value_num, "detail": m.value_json} for m in rows],
                indent=2, default=str,
            )

    return f"Unknown tool {name!r}."
