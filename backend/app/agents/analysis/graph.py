"""The analysis agent.

ONE graph serves both experimental arms. `arm` and `skill` are ordinary state
fields; they change the system prompt and nothing else. There is deliberately no
arm-conditional branch anywhere in the control flow — `test_experimental_fairness`
greps this module's source to keep it that way.

Loop shape:
    plan -> agent_step -> (tools -> agent_step)* -> summarize
`agent_step` calls the model; if it returns tool calls they are executed and fed
back, otherwise the run is finished. The iteration budget bounds it absolutely.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.analysis.prompts import (
    REPAIR_INSTRUCTION,
    build_system_prompt,
    build_task_prompt,
)
from app.agents.llm import Usage, llm
from app.agents.tools.sandbox_tools import TOOL_SCHEMAS, ToolContext, dispatch_tool
from app.config import settings
from app.sandbox.client import sandbox_client

logger = logging.getLogger(__name__)

Emitter = Callable[..., Awaitable[None]]


class AnalysisState(TypedDict, total=False):
    run_id: str
    arm: str
    task: str
    manifest_block: str
    skill: dict[str, Any] | None
    messages: list[dict[str, Any]]
    iterations: int
    max_iterations: int
    usage: dict[str, Any]
    summary: str
    error: str | None
    last_failed: bool
    # LangGraph only propagates keys declared on the state schema — a node that
    # returns an undeclared key has that key silently dropped. `_pending_calls`
    # is how agent_step hands tool calls to the tools node and to the router, so
    # it MUST be declared here even though it is internal.
    _pending_calls: list[Any]


async def _noop_emit(node, title, payload=None, kind="node", detail="") -> None:
    return None


def _dumps(obj: Any) -> str:
    try:
        return json.dumps(obj)
    except TypeError:
        return str(obj)


def build_analysis_graph(
    client=None,
    emit: Emitter | None = None,
    ctx: ToolContext | None = None,
    checkpointer=None,
):
    client = client or llm
    emit = emit or _noop_emit

    async def plan(state: AnalysisState) -> dict:
        arm = state["arm"]
        # DEVIATION FROM PLAN: the plan appended " using the paper-derived skill"
        # to this title behind an arm-equality test. That is literal
        # arm-conditional code in the graph — the thing the fairness suite exists
        # to forbid, and it fails the build on the source text — so the title is
        # now constant and the arm/skill facts travel in the payload, where the
        # UI can render them without the graph branching.
        await emit(
            "plan",
            "Planning the analysis",
            {"arm": arm, "has_skill": state.get("skill") is not None},
        )
        system = build_system_prompt(arm, state.get("skill"))
        user = build_task_prompt(state["task"], state["manifest_block"])
        return {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        }

    async def agent_step(state: AnalysisState) -> dict:
        messages = state["messages"]
        try:
            response = await client.chat(
                messages, tools=TOOL_SCHEMAS, temperature=settings.agent_temperature,
                max_tokens=16000,
            )
        except Exception as exc:
            logger.exception("model call failed")
            return {"error": f"{type(exc).__name__}: {exc}"}

        prior = state.get("usage") or {}
        merged = Usage(
            **{k: prior.get(k, 0) for k in
               ("prompt_tokens", "completion_tokens", "total_tokens", "cost")}
        ) + response.usage

        assistant: dict[str, Any] = {"role": "assistant", "content": response.content or ""}
        if response.tool_calls:
            assistant["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": _dumps(c.arguments)},
                }
                for c in response.tool_calls
            ]

        return {
            "messages": messages + [assistant],
            "usage": merged.to_dict(),
            "_pending_calls": response.tool_calls,
            "summary": response.content or state.get("summary", ""),
        }

    async def tools(state: AnalysisState) -> dict:
        pending = state.get("_pending_calls") or []
        messages = list(state["messages"])
        any_failure = False

        for call in pending:
            observation = await dispatch_tool(ctx, call.name, call.arguments)
            if call.name == "run_python" and "FAILED" in observation[:200]:
                any_failure = True
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "name": call.name,
                 "content": observation}
            )

        if any_failure:
            messages.append({"role": "user", "content": REPAIR_INSTRUCTION})

        return {
            "messages": messages,
            "iterations": state.get("iterations", 0) + 1,
            "_pending_calls": [],
            "last_failed": any_failure,
        }

    def route(state: AnalysisState) -> str:
        if state.get("error"):
            return "summarize"
        if state.get("iterations", 0) >= state.get("max_iterations", 8):
            return "summarize"
        return "tools" if state.get("_pending_calls") else "summarize"

    async def summarize(state: AnalysisState) -> dict:
        if state.get("error"):
            await emit("summarize", "Run failed", {"error": state["error"]}, kind="error")
            return {}

        exhausted = state.get("iterations", 0) >= state.get("max_iterations", 8)
        if exhausted:
            await emit(
                "summarize",
                "Iteration budget reached — asking for a final summary",
                {"iterations": state["iterations"]},
            )
            messages = state["messages"] + [
                {
                    "role": "user",
                    "content": (
                        "You have reached your step budget. Stop working and write a final "
                        "summary now: what you produced, the quantitative results, and what "
                        "is incomplete or uncertain."
                    ),
                }
            ]
            try:
                response = await client.chat(messages, temperature=0.0, max_tokens=4000)
                summary = response.content
            except Exception as exc:
                summary = state.get("summary") or f"Run ended without a summary: {exc}"
        else:
            summary = state.get("summary", "")

        await emit("summarize", "Analysis complete", {"chars": len(summary or "")})
        return {"summary": summary or ""}

    graph = StateGraph(AnalysisState)
    graph.add_node("plan", plan)
    graph.add_node("agent_step", agent_step)
    graph.add_node("tools", tools)
    graph.add_node("summarize", summarize)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "agent_step")
    graph.add_conditional_edges(
        "agent_step", route, {"tools": "tools", "summarize": "summarize"}
    )
    graph.add_edge("tools", "agent_step")
    graph.add_edge("summarize", END)

    # A checkpointer persists graph state at every super-step, keyed by the
    # run's thread id, so an interrupted run leaves an inspectable trail rather
    # than vanishing with the process. Optional by design: compile() with
    # checkpointer=None is the plain in-memory behaviour.
    return graph.compile(checkpointer=checkpointer)


async def run_analysis(
    run_id: str,
    arm: str,
    task: str,
    manifest_block: str,
    skill: dict[str, Any] | None = None,
    sandbox=None,
    client=None,
    emit: Emitter | None = None,
    max_iterations: int | None = None,
    checkpointer=None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    emit = emit or _noop_emit
    ctx = ToolContext(
        run_id=str(run_id), sandbox=sandbox or sandbox_client, emit=emit
    )
    graph = build_analysis_graph(
        client=client, emit=emit, ctx=ctx, checkpointer=checkpointer
    )

    budget = max_iterations or settings.agent_max_iterations
    config: dict[str, Any] = {
        # Each iteration costs two node visits (agent_step + tools); pad generously.
        "recursion_limit": budget * 3 + 12
    }
    if checkpointer is not None:
        # LangGraph requires a thread id whenever a checkpointer is attached;
        # keying it to the run makes the persisted state directly joinable to
        # the runs table via Run.thread_id.
        config["configurable"] = {"thread_id": str(thread_id or run_id)}

    final = await graph.ainvoke(
        {
            "run_id": str(run_id),
            "arm": arm,
            "task": task,
            "manifest_block": manifest_block,
            "skill": skill,
            "iterations": 0,
            "max_iterations": budget,
            "usage": {},
            "error": None,
        },
        config,
    )

    return {
        "summary": final.get("summary", ""),
        "artifacts": ctx.artifacts,
        "usage": final.get("usage", {}),
        "executions": ctx.executions,
        "failed_executions": ctx.failed_executions,
        "iterations": final.get("iterations", 0),
        "error": final.get("error"),
        "transcript": final.get("messages", []),
    }
