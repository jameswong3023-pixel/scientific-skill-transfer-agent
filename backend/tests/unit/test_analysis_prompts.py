import pytest

from app.agents.analysis.prompts import (
    SHARED_PREAMBLE,
    build_system_prompt,
    build_task_prompt,
)

SKILL = {
    "name": "BCFCM",
    "description": "Bias corrected fuzzy c-means",
    "intended_task": "Segment MRI",
    "modality": "MRI",
    "algorithm_steps": [
        {"order": 1, "operation": "Initialize centroids with k-means", "inferred": False}
    ],
    "parameters": [{"symbol": "alpha", "value": "0.7", "inferred": False}],
}


def test_base_arm_gets_the_shared_preamble():
    prompt = build_system_prompt("base", None)
    assert SHARED_PREAMBLE in prompt


def test_skill_arm_also_gets_the_identical_shared_preamble():
    prompt = build_system_prompt("skill", SKILL)
    assert SHARED_PREAMBLE in prompt


def test_base_prompt_contains_no_skill_content():
    prompt = build_system_prompt("base", None)
    assert "BCFCM" not in prompt
    assert "0.7" not in prompt
    assert "fuzzy" not in prompt.lower()


def test_skill_prompt_contains_the_technique_and_its_parameters():
    prompt = build_system_prompt("skill", SKILL)
    assert "BCFCM" in prompt
    assert "0.7" in prompt
    assert "k-means" in prompt


def test_the_only_difference_between_arms_is_the_appended_skill_block():
    base = build_system_prompt("base", None)
    skilled = build_system_prompt("skill", SKILL)
    assert skilled.startswith(base.split("## Available technique")[0].rstrip()[:200])
    assert len(skilled) > len(base)


def test_passing_a_skill_to_the_base_arm_is_refused():
    # A silent accept here would corrupt the experiment.
    with pytest.raises(ValueError, match="base arm"):
        build_system_prompt("base", SKILL)


def test_skill_arm_without_a_skill_is_refused():
    with pytest.raises(ValueError, match="skill arm"):
        build_system_prompt("skill", None)


def test_preamble_states_the_no_network_constraint():
    assert "no network" in SHARED_PREAMBLE.lower() or "no internet" in SHARED_PREAMBLE.lower()


def test_preamble_never_mentions_ground_truth():
    assert "ground truth" not in SHARED_PREAMBLE.lower()
    assert "ground_truth" not in SHARED_PREAMBLE.lower()


def test_task_prompt_includes_the_file_manifest():
    p = build_task_prompt("Segment the MRI", "Files available:\n  data/t1.nii.gz")
    assert "Segment the MRI" in p
    assert "data/t1.nii.gz" in p


def test_unknown_arm_rejected():
    with pytest.raises(ValueError):
        build_system_prompt("control", None)
