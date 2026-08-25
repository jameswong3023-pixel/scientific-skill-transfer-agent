from app.agents.conversation.graph import CONVERSATION_SYSTEM, answer
from app.agents.conversation.tools import CONVERSATION_TOOLS
from app.agents.llm import LLMResponse, ToolCallRequest, Usage


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools})
        return self.responses.pop(0)


class FakeCtx:
    def __init__(self):
        self.experiment_id = "e1"
        self.dispatched = []


async def fake_dispatch(ctx, name, args):
    ctx.dispatched.append(name)
    return f"result of {name}"


def test_tools_are_read_only():
    names = {t["function"]["name"] for t in CONVERSATION_TOOLS}
    assert names == {
        "get_experiment_summary", "get_skill", "list_artifacts",
        "read_artifact_text", "get_run_steps", "get_metrics",
    }
    # No mutation, and crucially no code execution from the chat surface.
    assert "run_python" not in names
    assert "write_file" not in names


def test_system_prompt_forbids_inventing_results():
    low = CONVERSATION_SYSTEM.lower()
    assert "do not invent" in low or "never invent" in low
    assert "tool" in low


async def test_direct_answer_without_tools():
    llm = ScriptedLLM([LLMResponse(content="The technique is BCFCM.", usage=Usage(total_tokens=10))])
    result = await answer("What technique was extracted?", [], FakeCtx(), client=llm,
                          dispatch=fake_dispatch)
    assert result["content"] == "The technique is BCFCM."
    assert result["tool_calls_made"] == []


async def test_agent_uses_tools_then_answers():
    llm = ScriptedLLM([
        LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(id="1", name="get_run_steps", arguments={"arm": "base"})],
            finish_reason="tool_calls",
            usage=Usage(total_tokens=20),
        ),
        LLMResponse(content="The first attempt failed on a shape mismatch.",
                    usage=Usage(total_tokens=15)),
    ])
    ctx = FakeCtx()
    result = await answer("Why did the first segmentation fail?", [], ctx, client=llm,
                          dispatch=fake_dispatch)
    assert "shape mismatch" in result["content"]
    assert result["tool_calls_made"] == ["get_run_steps"]


async def test_history_is_included_in_the_prompt():
    llm = ScriptedLLM([LLMResponse(content="Slice 72 shown.", usage=Usage(total_tokens=5))])
    history = [
        {"role": "user", "content": "Show me the segmentation"},
        {"role": "assistant", "content": "Here it is."},
    ]
    await answer("Now show slice 72.", history, FakeCtx(), client=llm, dispatch=fake_dispatch)
    blob = " ".join(str(m.get("content", "")) for m in llm.calls[0]["messages"])
    assert "Show me the segmentation" in blob


async def test_tool_loop_is_bounded():
    llm = ScriptedLLM([
        LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(id=str(i), name="get_metrics", arguments={})],
            finish_reason="tool_calls",
            usage=Usage(total_tokens=5),
        )
        for i in range(10)
    ] + [LLMResponse(content="final", usage=Usage(total_tokens=5))])
    result = await answer("q", [], FakeCtx(), client=llm, dispatch=fake_dispatch, max_tool_rounds=3)
    assert len(result["tool_calls_made"]) <= 3


async def test_model_error_returns_a_usable_message():
    class Broken:
        async def chat(self, *a, **k):
            raise RuntimeError("gateway down")

    result = await answer("q", [], FakeCtx(), client=Broken(), dispatch=fake_dispatch)
    assert "could not" in result["content"].lower() or "error" in result["content"].lower()
