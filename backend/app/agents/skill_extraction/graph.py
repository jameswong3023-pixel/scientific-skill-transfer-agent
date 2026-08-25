"""LangGraph pipeline: PDF pages -> validated, provenance-carrying Skill.

Branching and bounded retry live in the graph, not in an ad-hoc loop, so the
control flow is inspectable and every transition can emit a progress event.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.agents.llm import Usage, llm
from app.agents.skill_extraction.prompts import (
    EXTRACTION_SYSTEM,
    SEGMENT_SYSTEM,
    extraction_user_prompt,
)
from app.agents.skill_extraction.schema import EMIT_SKILL_TOOL, Skill, skill_to_markdown
from app.agents.skill_extraction.validate import validate_skill
from app.papers.ingest import ParsedPage, ParsedPaper

logger = logging.getLogger(__name__)

MAX_REPAIRS = 2
MAX_PAPER_CHARS = 600_000  # ox-alpha has a 1M-token window; this is comfortably inside it

Emitter = Callable[[str, str, dict[str, Any]], Awaitable[None]]


class SkillExtractionState(TypedDict, total=False):
    paper_id: str
    title: str | None
    pages: list[ParsedPage]
    methods_text: str
    draft: dict[str, Any]
    skill: Skill | None
    validation: dict[str, Any]
    repair_count: int
    markdown: str
    usage: dict[str, Any]
    error: str | None
    # LangGraph only propagates keys declared on the state schema — an undeclared
    # key returned by a node is silently dropped. validate_skill writes this and
    # extract_skill reads it on the repair pass, so it must be declared.
    _repair_prompt: str


async def _noop_emit(node: str, title: str, payload: dict[str, Any]) -> None:
    return None


def build_extraction_graph(client=None, emit: Emitter | None = None):
    client = client or llm
    emit = emit or _noop_emit

    async def segment_methods(state: SkillExtractionState) -> dict:
        pages: list[ParsedPage] = state["pages"]
        await emit("segment_methods", f"Reading {len(pages)} pages", {"pages": len(pages)})

        # With a 1M-token context the whole paper fits, so segmentation is an
        # optimisation, not a necessity. If it fails, fall back to everything.
        selected = pages
        if len(pages) > 6:
            index = "\n".join(
                f"[PAGE {p.page_number}] {p.text[:300]}" for p in pages
            )[:120_000]
            try:
                resp = await client.chat(
                    [
                        {"role": "system", "content": SEGMENT_SYSTEM},
                        {"role": "user", "content": index},
                    ],
                    max_tokens=200,
                    temperature=0.0,
                )
                wanted = {int(n) for n in re.findall(r"\d+", resp.content)}
                keep = [p for p in pages if p.page_number in wanted]
                if len(keep) >= 2:
                    selected = keep
            except Exception as exc:
                logger.warning("methods segmentation failed, using all pages: %s", exc)

        text = "\n\n".join(f"[PAGE {p.page_number}]\n{p.text}" for p in selected)
        await emit(
            "segment_methods",
            f"Focused on {len(selected)} methods pages",
            {"selected_pages": [p.page_number for p in selected]},
        )
        return {"methods_text": text[:MAX_PAPER_CHARS]}

    async def extract_skill(state: SkillExtractionState) -> dict:
        repair = state.get("repair_count", 0)
        title = (
            "Extracting the technique"
            if repair == 0
            else f"Repairing extraction (pass {repair})"
        )
        await emit("extract_skill", title, {"repair_count": repair})

        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM},
            {
                "role": "user",
                "content": extraction_user_prompt(state["methods_text"], state.get("title")),
            },
        ]
        repair_prompt = state.get("_repair_prompt") or ""
        if repair > 0 and repair_prompt:
            messages.append({"role": "assistant", "content": "(previous emit_skill call)"})
            messages.append({"role": "user", "content": repair_prompt})

        try:
            payload, usage = await client.structured(
                messages, EMIT_SKILL_TOOL, temperature=0.0, max_tokens=32000
            )
        except Exception as exc:
            logger.exception("extraction failed")
            return {"error": f"{type(exc).__name__}: {exc}"}

        prior = state.get("usage") or {}
        merged = (
            Usage(
                **{
                    k: prior.get(k, 0)
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens", "cost")
                }
            )
            + usage
        )
        return {"draft": payload, "usage": merged.to_dict()}

    async def validate_node(state: SkillExtractionState) -> dict:
        if state.get("error"):
            return {}
        draft = state.get("draft") or {}
        await emit("validate_skill", "Checking every citation against the paper", {})

        try:
            skill = Skill(**draft)
        except ValidationError as exc:
            report = {
                "ok": False,
                "verified_quotes": 0,
                "unverified_quotes": 0,
                "inferred_ratio": 0.0,
                "issues": [
                    {"severity": "error", "field": ".".join(str(x) for x in e["loc"]),
                     "message": e["msg"]}
                    for e in exc.errors()[:20]
                ],
            }
            repair_prompt = (
                "Your emit_skill arguments did not match the schema. "
                "Fix these and call it again:\n"
                + "\n".join(f"- {i['field']}: {i['message']}" for i in report["issues"])
            )
            return {"skill": None, "validation": report, "_repair_prompt": repair_prompt}

        report = validate_skill(skill, state["pages"])
        await emit(
            "validate_skill",
            f"{report.verified_quotes} quotes verified, {report.unverified_quotes} unverified",
            report.to_dict(),
        )
        return {
            "skill": skill,
            "validation": report.to_dict(),
            "_repair_prompt": report.as_repair_prompt(),
        }

    def route_after_validation(state: SkillExtractionState) -> str:
        if state.get("error"):
            return "finalize"
        validation = state.get("validation") or {}
        if validation.get("ok"):
            return "finalize"
        if state.get("repair_count", 0) >= MAX_REPAIRS:
            return "finalize"
        return "repair"

    async def repair(state: SkillExtractionState) -> dict:
        n = state.get("repair_count", 0) + 1
        await emit("repair_skill", f"Extraction had problems — repair pass {n}", {"pass": n})
        return {"repair_count": n}

    async def finalize(state: SkillExtractionState) -> dict:
        skill = state.get("skill")
        if skill is None:
            await emit("finalize", "Extraction failed", {"error": state.get("error")})
            return {"markdown": ""}
        md = skill_to_markdown(skill)
        await emit("finalize", f"Skill ready: {skill.name}", {"name": skill.name})
        return {"markdown": md}

    graph = StateGraph(SkillExtractionState)
    graph.add_node("segment_methods", segment_methods)
    graph.add_node("extract_skill", extract_skill)
    graph.add_node("validate_skill", validate_node)
    graph.add_node("repair", repair)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "segment_methods")
    graph.add_edge("segment_methods", "extract_skill")
    graph.add_edge("extract_skill", "validate_skill")
    graph.add_conditional_edges(
        "validate_skill", route_after_validation, {"repair": "repair", "finalize": "finalize"}
    )
    graph.add_edge("repair", "extract_skill")
    graph.add_edge("finalize", END)

    return graph.compile()


async def extract_skill_from_paper(
    parsed: ParsedPaper,
    paper_id: str,
    client=None,
    emit: Emitter | None = None,
) -> dict[str, Any]:
    graph = build_extraction_graph(client=client, emit=emit)
    final = await graph.ainvoke(
        {
            "paper_id": paper_id,
            "title": parsed.title,
            "pages": parsed.pages,
            "repair_count": 0,
            "usage": {},
            "error": None,
        },
        {"recursion_limit": 25},
    )
    return {
        "skill": final.get("skill"),
        "markdown": final.get("markdown", ""),
        "validation": final.get("validation", {"ok": False, "issues": []}),
        "usage": final.get("usage", {}),
        "repair_count": final.get("repair_count", 0),
        "error": final.get("error"),
    }
