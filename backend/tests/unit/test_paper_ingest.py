import fitz  # PyMuPDF
import pytest

from app.papers.ingest import (
    PdfParseError,
    find_quote,
    normalize_quote,
    parse_pdf,
)


def _pdf(pages: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 100), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def test_parses_pages_in_order():
    parsed = parse_pdf(_pdf(["First page body", "Second page body"]))
    assert len(parsed.pages) == 2
    assert parsed.pages[0].page_number == 1
    assert "First page" in parsed.pages[0].text
    assert "Second page" in parsed.pages[1].text


def test_char_counts_populated():
    parsed = parse_pdf(_pdf(["hello world"]))
    assert parsed.pages[0].char_count == len(parsed.pages[0].text)
    assert parsed.total_chars > 0


def test_detects_scanned_pdf_with_no_text_layer():
    doc = fitz.open()
    doc.new_page()  # blank, no text
    data = doc.tobytes()
    doc.close()
    assert parse_pdf(data).is_scanned is True


def test_renders_page_images_when_requested():
    parsed = parse_pdf(_pdf(["text here"]), render_pages=True)
    assert parsed.pages[0].image_png is not None
    assert parsed.pages[0].image_png[:8] == b"\x89PNG\r\n\x1a\n"


def test_corrupt_pdf_raises_typed_error():
    with pytest.raises(PdfParseError):
        parse_pdf(b"this is definitely not a pdf")


def test_empty_bytes_raises_typed_error():
    with pytest.raises(PdfParseError):
        parse_pdf(b"")


def test_normalize_collapses_whitespace_and_line_hyphens():
    assert normalize_quote("seg-\nmentation   of  the\tbrain") == "segmentation of the brain"
    assert normalize_quote("ﬁeld") == "field"


def test_find_quote_locates_the_right_page():
    parsed = parse_pdf(_pdf(["intro text", "we set alpha to 0.7 in all experiments"]))
    assert find_quote("we set alpha to 0.7", parsed.pages) == 2


def test_find_quote_survives_line_wrapping():
    parsed = parse_pdf(_pdf(["the bias field is estimated per voxel"]))
    assert find_quote("the bias\nfield  is estimated   per voxel", parsed.pages) == 1


def test_find_quote_returns_none_for_hallucination():
    parsed = parse_pdf(_pdf(["real content only"]))
    assert find_quote("we used a transformer with 12 heads", parsed.pages) is None
