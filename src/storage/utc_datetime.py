"""SQLAlchemy timestamp type with an explicit UTC normalization boundary."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UtcNaiveDateTime(TypeDecorator[datetime]):
    """Store UTC instants in PostgreSQL while preserving naive Python values.

    PostgreSQL uses timestamp-with-timezone columns. SQLite retains its
    timezone-naive storage contract. Naive Python values are interpreted as
    legacy UTC; aware values are normalized before binding. Results remain
    naive UTC during the repository compatibility transition.
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        return dialect.type_descriptor(DateTime(timezone=dialect.name == "postgresql"))

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError("UTC timestamp values must be datetime instances")
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        if dialect.name == "postgresql":
            return value
        return value.replace(tzinfo=None)

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)
