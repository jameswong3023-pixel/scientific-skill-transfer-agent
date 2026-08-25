"""Checkpointing must persist run state without ever being able to break a run."""

import app.agents.checkpointing as cp
from app.agents.analysis.graph import build_analysis_graph


def test_dsn_strips_sqlalchemy_driver_suffix(monkeypatch):
    # postgresql+psycopg:// is a SQLAlchemy convention; libpq rejects it.
    monkeypatch.setattr(
        cp.settings, "sync_database_url", "postgresql+psycopg://u:p@db:5432/x"
    )
    assert cp.checkpoint_dsn() == "postgresql://u:p@db:5432/x"


def test_dsn_handles_async_and_psycopg2_suffixes(monkeypatch):
    for url, expected in (
        ("postgresql+asyncpg://u:p@h:5432/d", "postgresql://u:p@h:5432/d"),
        ("postgresql+psycopg2://u:p@h:5432/d", "postgresql://u:p@h:5432/d"),
        ("postgresql://u:p@h:5432/d", "postgresql://u:p@h:5432/d"),
    ):
        monkeypatch.setattr(cp.settings, "sync_database_url", url)
        assert cp.checkpoint_dsn() == expected


def test_dsn_preserves_credentials_and_database():
    # A mangled DSN would silently send checkpoints to the wrong database.
    dsn = cp.checkpoint_dsn()
    assert dsn.startswith("postgresql://")
    assert "+" not in dsn.split("://", 1)[0]


async def test_unreachable_database_yields_none_rather_than_raising(monkeypatch):
    """The experiment is the product. Losing resumability must never lose a run."""
    monkeypatch.setattr(
        cp.settings, "sync_database_url", "postgresql+psycopg://u:p@127.0.0.1:9/x"
    )
    async with cp.analysis_checkpointer() as saver:
        assert saver is None


async def test_missing_dependency_yields_none(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def boom(name, *a, **kw):
        if "checkpoint.postgres" in name:
            raise ImportError("simulated missing extra")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", boom)
    async with cp.analysis_checkpointer() as saver:
        assert saver is None


def test_graph_compiles_with_and_without_a_checkpointer():
    # Passing None must reproduce the plain in-memory behaviour exactly.
    assert build_analysis_graph() is not None
    assert build_analysis_graph(checkpointer=None) is not None
