"""Wiring tests for the persistence layer, with the DB and object store stubbed.

`create_paper` and `persist_skill` are where three subsystems meet — PDF
parsing, MinIO keys, and the append-only skill_versions rule — and all three are
easy to get subtly wrong. Stubbing the session and the store keeps these true
unit tests (no stack, no network) while still exercising the real logic.
"""

import uuid

import fitz
import pytest

from app.agents.skill_extraction.schema import AlgorithmStep, Skill as SkillModel
from app.db.models import Paper, PaperPage, PaperStatus, Skill, SkillVersion
from app.papers.ingest import PdfParseError
from app.services import papers as svc


class FakeStore:
    def __init__(self):
        self.puts: dict[str, tuple[bytes, str]] = {}

    def put_bytes(self, key, data, content_type="application/octet-stream"):
        self.puts[key] = (data, content_type)
        return None


class FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class FakeSession:
    """Just enough AsyncSession to run the service functions."""

    def __init__(self, results=None):
        self.added: list[object] = []
        self.flushes = 0
        self._results = list(results or [])

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushes += 1

    async def execute(self, _stmt):
        return self._results.pop(0) if self._results else FakeResult([])

    async def get(self, _model, _pk):
        return None

    def of(self, cls):
        return [o for o in self.added if isinstance(o, cls)]


def _pdf(pages: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages:
        doc.new_page().insert_text((72, 100), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(svc, "store", fake)
    return fake


async def test_create_paper_persists_pages_and_marks_parsed(store):
    session = FakeSession()
    data = _pdf(["page one text", "page two text"])

    paper = await svc.create_paper(session, None, "methods.pdf", data)

    assert paper.status == PaperStatus.PARSED
    assert paper.page_count == 2
    assert paper.title  # derived from metadata or the first line
    rows = session.of(PaperPage)
    assert [r.page_number for r in rows] == [1, 2]
    assert "page one" in rows[0].text
    assert rows[0].char_count == len(rows[0].text)
    assert session.of(Paper) == [paper]


async def test_create_paper_stores_the_pdf_and_page_rasters_by_key(store):
    session = FakeSession()
    paper = await svc.create_paper(session, None, "methods.pdf", _pdf(["a page of text"]))

    assert paper.storage_key == f"papers/{paper.id}/source.pdf"
    assert store.puts[paper.storage_key][1] == "application/pdf"

    page_key = f"papers/{paper.id}/pages/001.png"
    assert store.puts[page_key][1] == "image/png"
    assert store.puts[page_key][0][:8] == b"\x89PNG\r\n\x1a\n"
    # The DB row must carry only the pointer, never the bytes.
    assert session.of(PaperPage)[0].image_storage_key == page_key


async def test_create_paper_records_the_sha256_of_the_upload(store):
    from app.storage.s3 import sha256_bytes

    data = _pdf(["content"])
    paper = await svc.create_paper(FakeSession(), None, "methods.pdf", data)
    assert paper.sha256 == sha256_bytes(data)


async def test_create_paper_marks_failed_when_the_pdf_is_corrupt(store):
    session = FakeSession()
    # Passes the magic-byte gate, then dies inside PyMuPDF.
    with pytest.raises(PdfParseError):
        await svc.create_paper(session, None, "broken.pdf", b"%PDF-1.4\nnot really a pdf")

    paper = session.of(Paper)[0]
    assert paper.status == PaperStatus.FAILED
    assert paper.error


async def test_create_paper_rejects_a_non_pdf_before_touching_storage(store):
    session = FakeSession()
    with pytest.raises(svc.UnsupportedUploadError):
        await svc.create_paper(session, None, "notes.pdf", b"PK\x03\x04zip")
    assert store.puts == {}, "nothing may be written for a rejected upload"
    assert session.added == []


def _skill_model() -> SkillModel:
    return SkillModel(
        name="Modified FCM",
        description="d",
        intended_task="segment",
        modality="MRI",
        algorithm_steps=[AlgorithmStep(order=1, operation="do it", inferred=True)],
    )


def _result() -> dict:
    return {
        "skill": _skill_model(),
        "markdown": "# Modified FCM",
        "validation": {"ok": True, "issues": []},
    }


async def test_persist_skill_creates_the_skill_and_version_one():
    paper = Paper(filename="p.pdf", storage_key="k", sha256="a" * 64)
    # 1st execute -> no existing Skill; 2nd -> no existing versions.
    session = FakeSession([FakeResult([]), FakeResult([])])

    version = await svc.persist_skill(session, paper, _result())

    skill = session.of(Skill)[0]
    assert skill.slug == "modified-fcm", "slug is lowercased and hyphenated"
    assert skill.paper_id == paper.id
    assert version.version == 1
    assert version.markdown == "# Modified FCM"
    assert version.payload["name"] == "Modified FCM"
    assert version.validation == {"ok": True, "issues": []}
    assert paper.status == PaperStatus.EXTRACTED


async def test_persist_skill_appends_a_new_version_to_an_existing_skill():
    paper = Paper(filename="p.pdf", storage_key="k", sha256="a" * 64)
    existing = Skill(paper_id=paper.id, name="Modified FCM", slug="modified-fcm")
    # 1st execute -> the existing Skill; 2nd -> versions 1 and 2 already present.
    session = FakeSession([FakeResult([existing]), FakeResult([1, 2])])

    version = await svc.persist_skill(session, paper, _result())

    assert session.of(Skill) == [], "an existing skill must be reused, not duplicated"
    assert version.skill_id == existing.id
    assert version.version == 3, "skill_versions is append-only"
    assert isinstance(version, SkillVersion)


async def test_persist_skill_refuses_a_failed_extraction():
    paper = Paper(filename="p.pdf", storage_key="k", sha256="a" * 64)
    with pytest.raises(ValueError, match="model exploded"):
        await svc.persist_skill(
            FakeSession(), paper, {"skill": None, "error": "model exploded"}
        )


async def test_persist_skill_payload_is_json_round_trippable():
    """Plan 04 reconstructs the skill with `Skill(**payload)`, so the dump must
    be pure JSON — a UUID or datetime in there would break that contract."""
    import json

    paper = Paper(filename="p.pdf", storage_key="k", sha256="a" * 64)
    session = FakeSession([FakeResult([]), FakeResult([])])
    version = await svc.persist_skill(session, paper, _result())

    round_tripped = SkillModel(**json.loads(json.dumps(version.payload)))
    assert round_tripped.name == "Modified FCM"
    assert isinstance(uuid.UUID(str(paper.id)), uuid.UUID)
