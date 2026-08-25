from app.agents.llm import Usage
from app.agents.skill_extraction.graph import extract_skill_from_paper
from app.papers.ingest import ParsedPage, ParsedPaper

PAPER_TEXT = (
    "We propose a modified fuzzy c-means. Centroids are initialized using k-means. "
    "We set the neighbourhood weight alpha = 0.7 in all experiments. "
    "The membership update is u_ik = 1 / sum_j (D_ik/D_jk)^(1/(p-1)). "
    "The algorithm halts when the change is below 0.001."
)


def _parsed() -> ParsedPaper:
    page = ParsedPage(page_number=1, text=PAPER_TEXT, char_count=len(PAPER_TEXT))
    return ParsedPaper(
        title="Modified FCM", pages=[page], total_chars=len(PAPER_TEXT), is_scanned=False
    )


def _good_skill_payload() -> dict:
    return {
        "name": "BCFCM",
        "description": "Bias corrected fuzzy c-means",
        "intended_task": "Segment MRI into tissue classes",
        "modality": "MRI",
        "required_dependencies": ["numpy", "nibabel"],
        "stopping_criteria": "change below 0.001",
        "parameters": [
            {"symbol": "alpha", "value": "0.7", "inferred": False,
             "provenance": {"quote": "We set the neighbourhood weight alpha = 0.7", "page": 1}}
        ],
        "algorithm_steps": [
            {"order": 1, "operation": "Initialize centroids", "inferred": False,
             "provenance": {"quote": "Centroids are initialized using k-means", "page": 1}},
            {"order": 2, "operation": "Update memberships", "inferred": False,
             "provenance": {"quote": "The membership update is u_ik = 1 / sum_j", "page": 1}},
            {"order": 3, "operation": "Test convergence", "inferred": False,
             "provenance": {"quote": "The algorithm halts when the change is below 0.001",
                            "page": 1}},
        ],
    }


class FakeLLM:
    """Records calls and returns queued structured payloads."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    async def structured(self, messages, tool_schema, **kwargs):
        self.calls.append({"messages": messages, "tool": tool_schema["name"]})
        return self.payloads.pop(0), Usage(total_tokens=100)

    async def chat(self, messages, **kwargs):
        from app.agents.llm import LLMResponse

        return LLMResponse(content="methods section is on page 1", usage=Usage(total_tokens=10))


async def test_happy_path_produces_a_validated_skill():
    fake = FakeLLM([_good_skill_payload()])
    result = await extract_skill_from_paper(_parsed(), "paper-1", client=fake)
    assert result["skill"].name == "BCFCM"
    assert result["validation"]["ok"] is True
    assert result["markdown"].startswith("# BCFCM")
    assert result["usage"]["total_tokens"] > 0


async def test_progress_events_are_emitted_in_order():
    seen: list[str] = []

    async def emit(node, title, payload):
        seen.append(node)

    await extract_skill_from_paper(
        _parsed(), "p", client=FakeLLM([_good_skill_payload()]), emit=emit
    )
    assert "extract_skill" in seen
    assert "validate_skill" in seen
    assert seen.index("extract_skill") < seen.index("validate_skill")


async def test_invalid_extraction_triggers_a_repair_pass():
    bad = _good_skill_payload()
    bad["algorithm_steps"] = [
        {"order": 1, "operation": "Apply a vision transformer", "inferred": False,
         "provenance": {"quote": "we trained a 12 layer vision transformer on ImageNet",
                        "page": 1}}
    ]
    fake = FakeLLM([bad, _good_skill_payload()])
    result = await extract_skill_from_paper(_parsed(), "p", client=fake)

    assert len(fake.calls) == 2, "a failed validation must trigger exactly one repair call"
    assert result["validation"]["ok"] is True
    assert result["repair_count"] == 1


async def test_repair_is_bounded():
    bad = _good_skill_payload()
    bad["algorithm_steps"] = [{"order": 1, "operation": "one step only", "inferred": True}]
    fake = FakeLLM([bad, bad, bad, bad])
    result = await extract_skill_from_paper(_parsed(), "p", client=fake)

    assert len(fake.calls) <= 3, "must not loop forever on an unfixable extraction"
    assert result["validation"]["ok"] is False
    assert result["skill"] is not None, "a flawed skill is still returned, flagged as invalid"


async def test_repair_prompt_contains_the_validation_errors():
    bad = _good_skill_payload()
    bad["algorithm_steps"] = [{"order": 1, "operation": "one", "inferred": True}]
    fake = FakeLLM([bad, _good_skill_payload()])
    await extract_skill_from_paper(_parsed(), "p", client=fake)

    repair_messages = fake.calls[1]["messages"]
    blob = " ".join(m["content"] for m in repair_messages if isinstance(m.get("content"), str))
    assert "algorithm_steps" in blob


async def test_schema_violation_from_model_is_handled():
    fake = FakeLLM([{"name": "X"}])  # missing required Skill fields
    result = await extract_skill_from_paper(_parsed(), "p", client=fake)
    assert result["error"] is not None or result["validation"]["ok"] is False


# --- segment_methods -------------------------------------------------------
# Only engages past 6 pages, so the 4-page integration fixture never reaches it.
# It decides which pages the extractor is allowed to see, and a bad fallback
# would silently starve extraction of the methods section.


class SegmentingLLM(FakeLLM):
    """FakeLLM whose `chat` (the segmentation call) is scriptable."""

    def __init__(self, payloads, segment_reply=None, segment_error=None):
        super().__init__(payloads)
        self.segment_reply = segment_reply
        self.segment_error = segment_error
        self.chat_calls = 0

    async def chat(self, messages, **kwargs):
        from app.agents.llm import LLMResponse

        self.chat_calls += 1
        if self.segment_error is not None:
            raise self.segment_error
        return LLMResponse(content=self.segment_reply or "", usage=Usage(total_tokens=10))


def _long_paper(n: int = 9) -> ParsedPaper:
    pages = [
        ParsedPage(
            page_number=i,
            text=f"{PAPER_TEXT} filler for page {i}",
            char_count=len(PAPER_TEXT),
        )
        for i in range(1, n + 1)
    ]
    return ParsedPaper(
        title="Long", pages=pages, total_chars=n * len(PAPER_TEXT), is_scanned=False
    )


def _paper_text_seen(fake: FakeLLM) -> str:
    """The paper body the extractor was actually shown."""
    return next(
        m["content"] for m in fake.calls[0]["messages"] if m["role"] == "user"
    )


async def test_short_paper_skips_the_segmentation_call_entirely():
    fake = SegmentingLLM([_good_skill_payload()], segment_reply="1")
    await extract_skill_from_paper(_parsed(), "p", client=fake)
    assert fake.chat_calls == 0, "a 1-page paper needs no segmentation"


async def test_long_paper_is_narrowed_to_the_selected_methods_pages():
    fake = SegmentingLLM([_good_skill_payload()], segment_reply="Pages 3, 4 and 5")
    await extract_skill_from_paper(_long_paper(), "p", client=fake)

    assert fake.chat_calls == 1
    seen = _paper_text_seen(fake)
    for kept in ("[PAGE 3]", "[PAGE 4]", "[PAGE 5]"):
        assert kept in seen
    for dropped in ("[PAGE 1]", "[PAGE 2]", "[PAGE 9]"):
        assert dropped not in seen


async def test_segmentation_failure_falls_back_to_the_whole_paper():
    fake = SegmentingLLM(
        [_good_skill_payload()], segment_error=RuntimeError("upstream rate limit")
    )
    await extract_skill_from_paper(_long_paper(), "p", client=fake)

    seen = _paper_text_seen(fake)
    for page in range(1, 10):
        assert f"[PAGE {page}]" in seen, "a failed segmentation must not lose pages"


async def test_useless_segmentation_answer_falls_back_to_the_whole_paper():
    """One page is not a methods section; treat a near-empty selection as failure."""
    fake = SegmentingLLM([_good_skill_payload()], segment_reply="4")
    await extract_skill_from_paper(_long_paper(), "p", client=fake)

    seen = _paper_text_seen(fake)
    assert "[PAGE 1]" in seen and "[PAGE 9]" in seen
