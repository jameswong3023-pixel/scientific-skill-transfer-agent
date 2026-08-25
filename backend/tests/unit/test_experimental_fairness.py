"""The A/B comparison is only meaningful if the arms are identical apart from
the skill. These tests encode that invariant so it cannot be quietly broken.
"""

import inspect

from app.agents.analysis import graph as graph_module
from app.agents.analysis.prompts import build_system_prompt
from app.agents.llm import LLMResponse, Usage
from app.agents.tools.sandbox_tools import TOOL_SCHEMAS


class RecordingLLM:
    def __init__(self):
        self.calls = []

    async def chat(self, messages, tools=None, tool_choice=None, temperature=None,
                   max_tokens=None, **kwargs):
        self.calls.append(
            {"tools": tools, "temperature": temperature, "max_tokens": max_tokens,
             "system": messages[0]["content"] if messages else ""}
        )
        return LLMResponse(content="done", usage=Usage(total_tokens=1))


class NullSandbox:
    async def execute(self, *a, **k):
        from app.sandbox.client import ExecutionResult

        return ExecutionResult(exit_code=0)

    async def list_files(self, run_id):
        return []

    async def read_file(self, run_id, path):
        return b""

    async def write_file(self, run_id, path, data):
        pass

    async def packages(self):
        return []


SKILL = {
    "name": "BCFCM", "description": "d", "intended_task": "t", "modality": "MRI",
    "algorithm_steps": [{"order": 1, "operation": "step", "inferred": False}],
}


async def _run(arm, skill):
    rec = RecordingLLM()
    await graph_module.run_analysis(
        "r1", arm, "the same task", "the same files",
        skill=skill, sandbox=NullSandbox(), client=rec, max_iterations=4,
    )
    return rec.calls[0]


async def test_both_arms_get_identical_tools():
    base = await _run("base", None)
    skilled = await _run("skill", SKILL)
    assert base["tools"] == skilled["tools"] == TOOL_SCHEMAS


async def test_both_arms_get_identical_sampling_parameters():
    base = await _run("base", None)
    skilled = await _run("skill", SKILL)
    assert base["temperature"] == skilled["temperature"]
    assert base["max_tokens"] == skilled["max_tokens"]


async def test_the_system_prompts_share_a_common_prefix():
    base = await _run("base", None)
    skilled = await _run("skill", SKILL)
    assert skilled["system"].startswith(base["system"])
    assert len(skilled["system"]) > len(base["system"])


async def test_only_the_skill_block_differs():
    base = build_system_prompt("base", None)
    skilled = build_system_prompt("skill", SKILL)
    assert skilled.replace(base, "", 1).lstrip().startswith("## Available technique")


def test_the_graph_has_no_arm_conditional_control_flow():
    source = inspect.getsource(graph_module)
    for forbidden in ('arm == "skill"', "arm == 'skill'", 'arm != "base"'):
        assert forbidden not in source, (
            f"found arm-conditional control flow ({forbidden}) in the analysis graph; "
            "the arms must differ only via build_system_prompt"
        )


def test_tool_list_is_not_parameterised_by_arm():
    source = inspect.getsource(graph_module.build_analysis_graph)
    assert "tools=TOOL_SCHEMAS" in source, "both arms must pass the same constant tool list"


async def test_the_same_iteration_budget_applies_to_both():
    rec_base, rec_skill = RecordingLLM(), RecordingLLM()
    for rec, arm, skill in ((rec_base, "base", None), (rec_skill, "skill", SKILL)):
        await graph_module.run_analysis(
            "r1", arm, "t", "f", skill=skill, sandbox=NullSandbox(), client=rec, max_iterations=5
        )
    assert len(rec_base.calls) == len(rec_skill.calls)
