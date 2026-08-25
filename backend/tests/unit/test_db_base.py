import uuid
from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Widget(Base):
    __tablename__ = "widgets_test"
    name: Mapped[str] = mapped_column(default="x")


def test_base_gives_uuid_pk_and_timestamp():
    w = Widget()
    assert isinstance(w.id, uuid.UUID)
    assert isinstance(w.created_at, datetime)


def test_two_instances_get_distinct_ids():
    assert Widget().id != Widget().id


def test_tablename_and_columns_registered():
    assert "widgets_test" in Base.metadata.tables
    cols = Base.metadata.tables["widgets_test"].columns
    assert "id" in cols and "created_at" in cols
