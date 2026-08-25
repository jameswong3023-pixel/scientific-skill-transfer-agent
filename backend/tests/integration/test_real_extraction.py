import os
from pathlib import Path

import pytest

from app.agents.skill_extraction.graph import extract_skill_from_paper
from app.papers.ingest import parse_pdf

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "sample_methods_paper.pdf"

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY"), reason="needs a real OpenRouter key"
)


async def test_real_model_extracts_a_usable_skill():
    parsed = parse_pdf(FIXTURE.read_bytes())
    assert len(parsed.pages) == 4

    result = await extract_skill_from_paper(parsed, "integration-paper")

    skill = result["skill"]
    assert skill is not None, f"extraction failed: {result.get('error')}"

    # It found the actual technique, not a generic description.
    assert "fuzzy" in skill.name.lower() or "fcm" in skill.name.lower()

    # It is implementable: enough steps to code from.
    assert len(skill.algorithm_steps) >= 3

    # It recovered the concrete parameters stated in the paper.
    symbols = {p.symbol.lower().lstrip("\\") for p in skill.parameters}
    assert "alpha" in symbols
    alpha = next(p for p in skill.parameters if p.symbol.lower().lstrip("\\") == "alpha")
    assert "0.7" in alpha.value

    # Citations are real: validation actually located the quotes in the PDF.
    assert result["validation"]["verified_quotes"] >= 1
    assert result["validation"]["unverified_quotes"] == 0, (
        f"model fabricated quotes: {result['validation']['issues']}"
    )

    # Honest about what it inferred.
    assert 0.0 <= result["validation"]["inferred_ratio"] < 1.0

    assert result["markdown"].startswith("#")
    assert result["usage"]["total_tokens"] > 0


async def test_extraction_captures_convergence_criteria():
    parsed = parse_pdf(FIXTURE.read_bytes())
    result = await extract_skill_from_paper(parsed, "integration-paper-2")
    skill = result["skill"]
    blob = (
        skill.stopping_criteria + " ".join(s.operation for s in skill.algorithm_steps)
    ).lower()
    assert "0.001" in blob or "converg" in blob
