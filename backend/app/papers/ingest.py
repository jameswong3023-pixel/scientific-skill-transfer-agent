from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# A page with fewer than this many characters of extracted text is treated as
# image-only. Scanned papers fall back to the model's vision capability.
SCANNED_CHAR_THRESHOLD = 100


class PdfParseError(Exception):
    """The upload could not be read as a PDF."""


@dataclass
class ParsedPage:
    page_number: int  # 1-based, matching how a human cites a paper
    text: str
    char_count: int
    image_png: bytes | None = None


@dataclass
class ParsedPaper:
    title: str | None
    pages: list[ParsedPage]
    total_chars: int
    is_scanned: bool

    def text_with_page_markers(self, max_chars: int | None = None) -> str:
        """Page markers are what let the model cite a page number it can be
        held to. Without them, provenance validation is impossible."""
        parts = [f"[PAGE {p.page_number}]\n{p.text}" for p in self.pages]
        joined = "\n\n".join(parts)
        return joined if max_chars is None else joined[:max_chars]


_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "­": ""}


def normalize_quote(s: str) -> str:
    """Make model-supplied quotes comparable to PDF-extracted text.

    PDF extraction introduces hard line breaks mid-word, ligatures, and erratic
    spacing; a model quoting the paper will silently repair all three. Matching
    raw strings would flag honest quotes as hallucinations.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    for lig, repl in _LIGATURES.items():
        s = s.replace(lig, repl)
    s = re.sub(r"-\s*\n\s*", "", s)          # de-hyphenate across line breaks
    s = re.sub(r"[‘’“”]", "'", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def parse_pdf(data: bytes, render_pages: bool = False, max_render: int = 12) -> ParsedPaper:
    import fitz

    if not data:
        raise PdfParseError("empty upload")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise PdfParseError(f"could not open PDF: {type(exc).__name__}: {exc}") from exc

    try:
        if doc.page_count == 0:
            raise PdfParseError("PDF contains no pages")

        pages: list[ParsedPage] = []
        for i in range(doc.page_count):
            page = None
            try:
                page = doc.load_page(i)
                text = page.get_text("text") or ""
            except Exception as exc:
                logger.warning("page %d unreadable: %s", i + 1, exc)
                text = ""

            image_png = None
            if render_pages and page is not None and i < max_render:
                try:
                    pix = page.get_pixmap(dpi=140)
                    image_png = pix.tobytes("png")
                except Exception as exc:
                    logger.warning("could not raster page %d: %s", i + 1, exc)

            pages.append(
                ParsedPage(
                    page_number=i + 1,
                    text=text,
                    char_count=len(text),
                    image_png=image_png,
                )
            )

        total = sum(p.char_count for p in pages)
        avg = total / max(len(pages), 1)
        title = (doc.metadata or {}).get("title") or None
        if not title and pages and pages[0].text:
            first = [ln.strip() for ln in pages[0].text.splitlines() if ln.strip()]
            title = first[0][:400] if first else None

        return ParsedPaper(
            title=title,
            pages=pages,
            total_chars=total,
            is_scanned=avg < SCANNED_CHAR_THRESHOLD,
        )
    finally:
        doc.close()


def find_quote(quote: str, pages: list[ParsedPage]) -> int | None:
    """Page number containing `quote`, or None. Used to catch fabricated citations."""
    needle = normalize_quote(quote)
    if len(needle) < 12:
        return None  # too short to be evidence of anything
    for page in pages:
        if needle in normalize_quote(page.text):
            return page.page_number
    return None
