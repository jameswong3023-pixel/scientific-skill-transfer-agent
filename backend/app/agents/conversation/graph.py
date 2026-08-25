from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.conversation.tools import CONVERSATION_TOOLS, dispatch_conversation_tool
from app.agents.llm import llm

logger = logging.getLogger(__name__)

CONVERSATION_SYSTEM = """You are the scientific agent that ran this experiment, answering \
questions about it.

You have read-only tools that return the real record: the extracted skill with its \
provenance, both agents' execution timelines, their generated code, their outputs, and the \
computed metrics.

Rules:
- Never invent results. If you have not read a value with a tool, look it up before quoting it.
- When asked why something failed, read the run steps and quote the actual error.
- When asked where a parameter came from, check the skill's provenance and say whether it was \
quoted from the paper or inferred.
- Distinguish clearly between the base agent and the skill-enabled agent.
- Be concise and specific. Prefer concrete numbers, filenames and error messages over \
generalities.
- If the data does not answer the question, say so plainly."""

MAX_TOOL_ROUNDS = 5


async def answer(
    question: str,
    history: list[dict[str, Any]],
    ctx,
    client=None,
    dispatch=None,
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
) -> dict[str, Any]:
    client = client or llm
    dispatch = dispatch or dispatch_conversation_tool

    messages: list[dict[str, Any]] = [{"role": "system", "content": CONVERSATION_SYSTEM}]
    messages.extend(history[-20:])
    messages.append({"role": "user", "content": question})

    used: list[str] = []

    for _ in range(max_tool_rounds + 1):
        try:
            response = await client.chat(
                messages, tools=CONVERSATION_TOOLS, temperature=0.2, max_tokens=4000
            )
        except Exception as exc:
            logger.exception("conversation model call failed")
            return {
                "content": f"I could not reach the model to answer that ({type(exc).__name__}). "
                           f"Please try again.",
                "tool_calls_made": used,
            }

        if not response.tool_calls:
            return {"content": response.content, "tool_calls_made": used}

        if len(used) >= max_tool_rounds:
            messages.append(
                {"role": "user",
                 "content": "Stop calling tools and answer with what you have."}
            )
            try:
                final = await client.chat(messages, temperature=0.2, max_tokens=2000)
                return {"content": final.content, "tool_calls_made": used}
            except Exception:
                return {"content": "I ran out of lookups before I could answer.",
                        "tool_calls_made": used}

        messages.append(
            {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                    for c in response.tool_calls
                ],
            }
        )
        for call in response.tool_calls:
            used.append(call.name)
            try:
                observation = await dispatch(ctx, call.name, call.arguments)
            except Exception as exc:
                observation = f"Tool error: {type(exc).__name__}: {exc}"
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "name": call.name,
                 "content": observation}
            )

    return {"content": "I was unable to complete that answer.", "tool_calls_made": used}
