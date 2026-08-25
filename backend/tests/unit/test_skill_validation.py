from app.agents.skill_extraction.schema import (
    AlgorithmStep,
    Parameter,
    Provenance,
    Skill,
)
from app.agents.skill_extraction.validate import validate_skill
from app.papers.ingest import ParsedPage


def _pages() -> list[ParsedPage]:
    text = (
        "We set the neighbourhood weight alpha = 0.7 in all experiments. "
        "Centroids are initialized using k-means. "
        "The algorithm halts when the change is below 0.001."
    )
    return [ParsedPage(page_number=1, text=text, char_count=len(text))]


def _skill(**overrides) -> Skill:
    base = dict(
        name="BCFCM",
        description="d",
        intended_task="segment",
        modality="MRI",
        algorithm_steps=[
            AlgorithmStep(
                order=1, operation="Initialize centroids", inferred=False,
                provenance=Provenance(quote="Centroids are initialized using k-means", page=1),
            ),
            AlgorithmStep(order=2, operation="Update memberships", inferred=True),
            AlgorithmStep(
                order=3, operation="Check convergence", inferred=False,
                provenance=Provenance(
                    quote="The algorithm halts when the change is below 0.001", page=1
                ),
            ),
        ],
    )
    base.update(overrides)
    return Skill(**base)


def test_valid_skill_passes():
    report = validate_skill(_skill(), _pages())
    assert report.ok is True
    assert report.verified_quotes == 2


def test_fabricated_quote_is_an_error():
    skill = _skill(algorithm_steps=[
        AlgorithmStep(
            order=1, operation="Apply a transformer", inferred=False,
            provenance=Provenance(quote="we trained a 12-layer vision transformer", page=1),
        ),
        AlgorithmStep(order=2, operation="b", inferred=True),
        AlgorithmStep(order=3, operation="c", inferred=True),
    ])
    report = validate_skill(skill, _pages())
    assert report.ok is False
    assert any("not found" in i.message.lower() for i in report.issues)
    assert report.unverified_quotes >= 1


def test_wrong_page_number_is_reported_but_recoverable():
    skill = _skill(algorithm_steps=[
        AlgorithmStep(
            order=1, operation="Initialize", inferred=False,
            provenance=Provenance(quote="Centroids are initialized using k-means", page=7),
        ),
        AlgorithmStep(order=2, operation="b", inferred=True),
        AlgorithmStep(order=3, operation="c", inferred=True),
    ])
    report = validate_skill(skill, _pages())
    assert any("page" in i.message.lower() for i in report.issues)


def test_too_few_algorithm_steps_is_an_error():
    skill = _skill(algorithm_steps=[AlgorithmStep(order=1, operation="do everything")])
    report = validate_skill(skill, _pages())
    assert report.ok is False
    assert any("algorithm_steps" in i.field for i in report.issues)


def test_steps_must_be_ordered_without_gaps():
    skill = _skill(algorithm_steps=[
        AlgorithmStep(order=1, operation="a", inferred=True),
        AlgorithmStep(order=5, operation="b", inferred=True),
        AlgorithmStep(order=9, operation="c", inferred=True),
    ])
    report = validate_skill(skill, _pages())
    assert any("order" in i.message.lower() for i in report.issues)


def test_inferred_ratio_is_computed():
    report = validate_skill(_skill(), _pages())
    assert 0.0 < report.inferred_ratio < 1.0


def test_everything_inferred_is_a_warning_not_a_pass():
    skill = _skill(algorithm_steps=[
        AlgorithmStep(order=i, operation=f"step {i}", inferred=True) for i in (1, 2, 3)
    ])
    report = validate_skill(skill, _pages())
    assert report.inferred_ratio == 1.0
    assert any(i.severity == "warning" for i in report.issues)


def test_repair_prompt_names_the_problems():
    skill = _skill(algorithm_steps=[AlgorithmStep(order=1, operation="only one")])
    prompt = validate_skill(skill, _pages()).as_repair_prompt()
    assert "algorithm_steps" in prompt
    assert len(prompt) > 40


def test_parameter_quotes_are_validated_too():
    skill = _skill(parameters=[
        Parameter(
            symbol="alpha", value="0.7", inferred=False,
            provenance=Provenance(quote="never appeared in this paper at all", page=1),
        )
    ])
    report = validate_skill(skill, _pages())
    assert any("parameters" in i.field for i in report.issues)
