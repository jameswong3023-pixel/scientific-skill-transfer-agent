import pytest
from pydantic import ValidationError

from app.agents.skill_extraction.schema import (
    EMIT_SKILL_TOOL,
    AlgorithmStep,
    Parameter,
    Provenance,
    Skill,
    skill_to_markdown,
)


def _minimal() -> dict:
    return {
        "name": "BCFCM",
        "description": "Bias-corrected fuzzy c-means",
        "intended_task": "Segment MRI into tissue classes",
        "modality": "MRI",
        "algorithm_steps": [
            {"order": 1, "operation": "Initialize centroids", "inferred": False,
             "provenance": {"quote": "centroids are initialized by k-means", "page": 3}},
        ],
    }


def test_minimal_skill_validates():
    s = Skill(**_minimal())
    assert s.name == "BCFCM"
    assert s.algorithm_steps[0].order == 1


def test_missing_required_field_rejected():
    bad = _minimal()
    del bad["intended_task"]
    with pytest.raises(ValidationError):
        Skill(**bad)


def test_list_fields_default_to_empty_not_none():
    s = Skill(**_minimal())
    assert s.parameters == []
    assert s.known_failure_modes == []
    assert s.validation_checks == []


def test_inferred_defaults_to_false():
    step = AlgorithmStep(order=1, operation="do a thing")
    assert step.inferred is False


def test_provenance_requires_a_page():
    with pytest.raises(ValidationError):
        Provenance(quote="something said in the paper")


def test_parameter_records_whether_it_was_inferred():
    p = Parameter(symbol="alpha", value="0.7", inferred=False,
                  provenance=Provenance(quote="we set alpha = 0.7", page=4))
    assert p.inferred is False
    assert p.provenance.page == 4


def test_emit_tool_is_a_valid_openrouter_function_schema():
    assert EMIT_SKILL_TOOL["name"] == "emit_skill"
    params = EMIT_SKILL_TOOL["parameters"]
    assert params["type"] == "object"
    for required in ("name", "description", "intended_task", "algorithm_steps"):
        assert required in params["properties"]
        assert required in params["required"]


def test_emit_tool_asks_for_provenance_on_steps():
    step_schema = EMIT_SKILL_TOOL["parameters"]["properties"]["algorithm_steps"]["items"]
    assert "provenance" in step_schema["properties"]
    assert "inferred" in step_schema["properties"]


def test_markdown_render_includes_key_sections():
    md = skill_to_markdown(Skill(**_minimal()))
    for heading in ("# BCFCM", "## Intended task", "## Algorithm", "## Parameters"):
        assert heading in md


def test_markdown_marks_inferred_content():
    data = _minimal()
    data["algorithm_steps"].append(
        {"order": 2, "operation": "Guessed step", "inferred": True}
    )
    md = skill_to_markdown(Skill(**data))
    assert "inferred" in md.lower()
