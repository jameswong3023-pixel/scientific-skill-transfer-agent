from app.agents.analysis.graph import run_analysis
from app.agents.llm import LLMResponse, ToolCallRequest, Usage
from app.sandbox.client import ExecutionResult


class ScriptedLLM:
    """Replays a queue of responses and records what it was asked."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, messages, tools=None, tool_choice=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools})
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="Done.", usage=Usage(total_tokens=5))


class FakeSandbox:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = 0

    async def execute(self, run_id, code=None, filename="script.py", argv=None, timeout_s=None):
        self.calls += 1
        if self.results:
            return self.results.pop(0)
        return ExecutionResult(exit_code=0, stdout="ok", duration_ms=5)

    async def list_files(self, run_id):
        return [{"path": "data/t1.nii.gz", "bytes": 1000}]

    async def read_file(self, run_id, path):
        return b"text"

    async def write_file(self, run_id, path, data):
        pass

    async def packages(self):
        return [{"name": "numpy", "version": "2.2.1"}]


def _tool_response(name, args, tid="t1"):
    return LLMResponse(
        content="",
        tool_calls=[ToolCallRequest(id=tid, name=name, arguments=args)],
        finish_reason="tool_calls",
        usage=Usage(total_tokens=50),
    )


async def test_agent_runs_code_and_finishes():
    llm = ScriptedLLM([
        _tool_response("run_python", {"code": "print(1)", "filename": "a.py"}),
        _tool_response("save_artifact", {"path": "outputs/seg.nii.gz", "kind": "output"}),
        LLMResponse(content="Segmentation complete. Volumes computed.",
                    usage=Usage(total_tokens=20)),
    ])
    sandbox = FakeSandbox()
    result = await run_analysis(
        "r1", "base", "Segment the MRI", "Files:\n data/t1.nii.gz",
        sandbox=sandbox, client=llm,
    )
    assert result["error"] is None
    assert result["executions"] == 1
    assert "Segmentation complete" in result["summary"]
    assert result["artifacts"][0]["path"] == "outputs/seg.nii.gz"


async def test_failed_execution_triggers_a_repair_iteration():
    llm = ScriptedLLM([
        _tool_response("run_python", {"code": "boom", "filename": "a.py"}),
        _tool_response("run_python", {"code": "fixed", "filename": "a.py"}, tid="t2"),
        LLMResponse(content="Recovered and finished.", usage=Usage(total_tokens=10)),
    ])
    sandbox = FakeSandbox([
        ExecutionResult(exit_code=1, stderr="ValueError: shape mismatch", duration_ms=4),
        ExecutionResult(exit_code=0, stdout="worked", duration_ms=9),
    ])
    result = await run_analysis(
        "r1", "base", "task", "files", sandbox=sandbox, client=llm
    )
    assert sandbox.calls == 2
    assert result["failed_executions"] == 1
    assert result["error"] is None


async def test_stderr_is_fed_back_to_the_model():
    llm = ScriptedLLM([
        _tool_response("run_python", {"code": "boom"}),
        LLMResponse(content="done", usage=Usage(total_tokens=5)),
    ])
    sandbox = FakeSandbox([
        ExecutionResult(exit_code=1, stderr="KeyError: 'affine'", duration_ms=3)
    ])
    await run_analysis("r1", "base", "t", "f", sandbox=sandbox, client=llm)

    last_messages = llm.calls[-1]["messages"]
    blob = " ".join(str(m.get("content", "")) for m in last_messages)
    assert "KeyError: 'affine'" in blob


async def test_iteration_budget_is_enforced():
    # A model that never stops calling tools must still terminate.
    llm = ScriptedLLM([_tool_response("run_python", {"code": f"print({i})"}) for i in range(50)])
    sandbox = FakeSandbox()
    result = await run_analysis(
        "r1", "base", "t", "f", sandbox=sandbox, client=llm, max_iterations=3
    )
    assert result["iterations"] <= 3
    assert sandbox.calls <= 3


async def test_progress_events_are_emitted():
    seen = []

    async def emit(node, title, payload=None, kind="node", detail=""):
        seen.append((node, title))

    llm = ScriptedLLM([LLMResponse(content="done", usage=Usage(total_tokens=5))])
    await run_analysis("r1", "base", "t", "f", sandbox=FakeSandbox(), client=llm, emit=emit)
    nodes = [n for n, _ in seen]
    assert "plan" in nodes
    assert "summarize" in nodes


async def test_both_arms_receive_identical_tool_schemas():
    from app.agents.tools.sandbox_tools import TOOL_SCHEMAS

    for arm, skill in (("base", None), ("skill", {"name": "X", "description": "d",
                                                  "intended_task": "t", "modality": "MRI",
                                                  "algorithm_steps": []})):
        llm = ScriptedLLM([LLMResponse(content="done", usage=Usage(total_tokens=1))])
        await run_analysis("r1", arm, "t", "f", skill=skill, sandbox=FakeSandbox(), client=llm)
        assert llm.calls[0]["tools"] == TOOL_SCHEMAS


async def test_model_failure_is_captured_not_raised():
    class BrokenLLM:
        async def chat(self, *a, **k):
            raise RuntimeError("openrouter down")

    result = await run_analysis("r1", "base", "t", "f", sandbox=FakeSandbox(), client=BrokenLLM())
    assert result["error"] is not None
    assert "openrouter down" in result["error"]


async def test_usage_is_accumulated_across_iterations():
    llm = ScriptedLLM([
        _tool_response("run_python", {"code": "x"}),
        LLMResponse(content="done", usage=Usage(total_tokens=30)),
    ])
    result = await run_analysis("r1", "base", "t", "f", sandbox=FakeSandbox(), client=llm)
    assert result["usage"]["total_tokens"] >= 80
