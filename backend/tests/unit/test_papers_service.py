import pytest

from app.services.papers import UnsupportedUploadError, validate_pdf_upload


def _valid_pdf() -> bytes:
    import fitz

    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "hello")
    data = doc.tobytes()
    doc.close()
    return data


def test_accepts_a_real_pdf():
    validate_pdf_upload("paper.pdf", _valid_pdf())  # must not raise


def test_rejects_wrong_magic_bytes():
    with pytest.raises(UnsupportedUploadError, match="not a PDF"):
        validate_pdf_upload("paper.pdf", b"PK\x03\x04 this is a zip")


def test_rejects_wrong_extension():
    with pytest.raises(UnsupportedUploadError, match="extension"):
        validate_pdf_upload("paper.docx", _valid_pdf())


def test_rejects_empty_upload():
    with pytest.raises(UnsupportedUploadError):
        validate_pdf_upload("paper.pdf", b"")


def test_rejects_oversized_upload():
    from app.services.papers import MAX_PDF_BYTES

    with pytest.raises(UnsupportedUploadError, match="too large"):
        validate_pdf_upload("paper.pdf", b"%PDF-1.4" + b"0" * (MAX_PDF_BYTES + 1))


def test_next_version_starts_at_one():
    from app.services.papers import compute_next_version

    assert compute_next_version([]) == 1
    assert compute_next_version([1, 2, 3]) == 4
    assert compute_next_version([2]) == 3
