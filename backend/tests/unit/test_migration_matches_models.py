"""Guard against migration/model drift without needing a live database.

`alembic revision --autogenerate` diffs the models against a real Postgres. That
is not available during unit tests, so this parses the migration script instead
and asserts it creates exactly the tables and columns the models declare. If
someone adds a column to a model and forgets the migration, this fails.
"""

import ast
from pathlib import Path

from app.db import models  # noqa: F401  registers every table on Base.metadata
from app.db.base import Base

MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0001_initial.py"
)


def _domain_tables() -> dict[str, set[str]]:
    """Tables declared by app.db.models, keyed to their column names.

    Deliberately not `Base.metadata.tables`: other test modules define throwaway
    models against the same Base to exercise it, and those register real tables
    on the shared metadata. Only classes living under app.db.models are part of
    the schema the migration is responsible for.
    """
    result: dict[str, set[str]] = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if not cls.__module__.startswith("app.db.models"):
            continue
        table = mapper.local_table
        result[table.name] = set(table.columns.keys())
    return result


def _const(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _calls(tree: ast.AST, name: str) -> list[ast.Call]:
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == name
        ):
            found.append(node)
    return found


def _parsed() -> ast.AST:
    return ast.parse(MIGRATION.read_text(encoding="utf-8"))


def _created_tables() -> dict[str, set[str]]:
    """Map table name -> column names, as declared by op.create_table calls."""
    tables: dict[str, set[str]] = {}
    for call in _calls(_parsed(), "create_table"):
        if not call.args:
            continue
        name = _const(call.args[0])
        if name is None:
            continue
        columns = set()
        for arg in call.args[1:]:
            if (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Attribute)
                and arg.func.attr == "Column"
                and arg.args
            ):
                col = _const(arg.args[0])
                if col:
                    columns.add(col)
        tables[name] = columns
    return tables


def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration at {MIGRATION}"


def test_migration_creates_every_model_table():
    declared = set(_domain_tables())
    created = set(_created_tables())
    assert created == declared, (
        f"missing from migration: {declared - created}; "
        f"in migration but not in models: {created - declared}"
    )


def test_migration_columns_match_models_exactly():
    created = _created_tables()
    mismatches: dict[str, dict[str, set[str]]] = {}
    for name, declared in _domain_tables().items():
        actual = created.get(name, set())
        if declared != actual:
            mismatches[name] = {"missing": declared - actual, "extra": actual - declared}
    assert not mismatches, f"migration/model column drift: {mismatches}"


def test_downgrade_drops_everything_upgrade_creates():
    tree = _parsed()
    dropped = {_const(c.args[0]) for c in _calls(tree, "drop_table") if c.args}
    assert dropped == set(_created_tables()), (
        "downgrade must be a complete inverse of upgrade; "
        f"difference: {dropped ^ set(_created_tables())}"
    )


def test_revision_is_the_pinned_initial_id():
    tree = _parsed()
    assignments = {
        node.target.id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert _const(assignments["revision"]) == "0001_initial"
    assert isinstance(assignments["down_revision"], ast.Constant)
    assert assignments["down_revision"].value is None, "initial migration has no parent"
