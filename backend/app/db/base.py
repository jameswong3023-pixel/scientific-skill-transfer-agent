import inspect as pyinspect
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Every table gets a UUID primary key and a creation timestamp.

    UUIDs are generated client-side so that a caller can reference a row
    (e.g. build an object-storage key from it) before the INSERT lands.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


_UNSET = object()


def _resolve_default(default: Any) -> Any:
    """Evaluate a Python-side column default to a concrete value.

    Returns `_UNSET` for anything only the database can produce (server_default,
    SQL expressions, sequences), which must be left for the INSERT to fill in.
    """
    if default is None:
        return _UNSET
    if getattr(default, "is_callable", False):
        fn = default.arg
        # SQLAlchemy wraps callable defaults so they accept an ExecutionContext,
        # and the wrapper carries functools.wraps metadata. That means a plain
        # signature() call reports the *original* function's parameters (uuid4
        # takes none) while the object actually invoked demands a ctx argument.
        # follow_wrapped=False reads the wrapper's real signature instead.
        # There is no ExecutionContext at construction time, so None is passed.
        try:
            takes_context = bool(
                pyinspect.signature(fn, follow_wrapped=False).parameters
            )
        except (TypeError, ValueError):
            takes_context = True
        return fn(None) if takes_context else fn()
    if getattr(default, "is_scalar", False):
        return default.arg
    return _UNSET


@event.listens_for(Base, "init", propagate=True)
def _apply_defaults_at_construction(
    target: Base, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> None:
    """Populate Python-side column defaults when the object is constructed.

    SQLAlchemy normally applies `default=` during flush, so a freshly built
    `Paper()` would have `id=None` and `status=None` until the INSERT lands.
    Two things depend on those values existing immediately:

    * Services derive object-storage keys from `row.id` before saving the row
      (see app/services/papers.py), so the id must be real, not None.
    * Status and role fields are read back by callers before anything flushes.

    The `default=` on each column stays in place as a backstop for rows created
    by paths that bypass the constructor, such as bulk inserts.

    Note: defining `__init__` on Base does NOT work for this. The declarative
    constructor is installed onto each mapped subclass, so an override on Base
    is shadowed and `super().__init__()` falls through to `object.__init__`.
    """
    mapper = sa_inspect(type(target), raiseerr=False)
    if mapper is None:
        return
    for column in mapper.columns:
        try:
            key = mapper.get_property_by_column(column).key
        except Exception:
            continue
        if key in kwargs:
            continue
        value = _resolve_default(column.default)
        if value is not _UNSET:
            kwargs[key] = value
