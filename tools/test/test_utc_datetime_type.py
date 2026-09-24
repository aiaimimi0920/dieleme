from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, MetaData, Table, create_engine, insert, select
from sqlalchemy.dialects import postgresql

from src.storage.models import Base, PropertyAudit, PropertyListing
from src.storage.utc_datetime import UtcNaiveDateTime

SEMANTIC_DATETIME_EXCEPTIONS = {
    ("property_listing", "auction_date"),
    ("property_listing", "auction_start_time"),
    ("property_legal_context", "appraisal_benchmark_date"),
}


def test_utc_naive_datetime_normalizes_aware_values_on_sqlite_round_trip():
    metadata = MetaData()
    table = Table("timestamps", metadata, Column("value", UtcNaiveDateTime()))
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    aware = datetime(2026, 9, 22, 12, 34, 56, tzinfo=timezone(timedelta(hours=8)))
    naive = datetime.fromisoformat("2026-09-22T04:34:56")

    with engine.begin() as connection:
        connection.execute(insert(table), [{"value": aware}, {"value": naive}])
        values = connection.execute(select(table.c.value).order_by(table.c.value)).scalars().all()

    assert values == [naive, naive]
    assert all(value.tzinfo is None for value in values)


def test_utc_naive_datetime_uses_aware_postgresql_storage():
    type_ = UtcNaiveDateTime()
    sqlite_type = type_.load_dialect_impl(create_engine("sqlite://").dialect)
    postgres_type = type_.load_dialect_impl(postgresql.dialect())

    assert isinstance(sqlite_type, DateTime)
    assert isinstance(postgres_type, DateTime)
    assert sqlite_type.timezone is False
    assert postgres_type.timezone is True


def test_postgresql_bind_normalizes_legacy_and_aware_values_to_utc():
    type_ = UtcNaiveDateTime()
    dialect = postgresql.dialect()
    legacy = datetime(2026, 9, 22, 4, 34, 56)
    aware = datetime(2026, 9, 22, 12, 34, 56, tzinfo=timezone(timedelta(hours=8)))
    expected = datetime(2026, 9, 22, 4, 34, 56, tzinfo=timezone.utc)

    assert type_.process_bind_param(legacy, dialect) == expected
    assert type_.process_bind_param(aware, dialect) == expected
    assert type_.process_result_value(aware, dialect) == legacy


def test_system_timestamp_columns_use_utc_normalization_boundary():
    assert isinstance(PropertyListing.__table__.c.created_at.type, UtcNaiveDateTime)
    assert isinstance(PropertyAudit.__table__.c.detail_lease_until.type, UtcNaiveDateTime)
    assert PropertyListing.__table__.c.auction_date.type.timezone is False


def test_metadata_datetime_columns_have_explicit_utc_boundary():
    datetime_columns = {
        (table.name, column.name): column
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, (DateTime, UtcNaiveDateTime))
    }
    native_datetime_keys = {
        key
        for key, column in datetime_columns.items()
        if not isinstance(column.type, UtcNaiveDateTime)
    }

    assert native_datetime_keys == SEMANTIC_DATETIME_EXCEPTIONS
    for key, column in datetime_columns.items():
        if key not in SEMANTIC_DATETIME_EXCEPTIONS:
            assert isinstance(column.type, UtcNaiveDateTime), key
            assert column.type.load_dialect_impl(postgresql.dialect()).timezone is True, key


def test_semantic_datetime_exceptions_remain_legacy_naive_types():
    for table_name, column_name in SEMANTIC_DATETIME_EXCEPTIONS:
        column = Base.metadata.tables[table_name].columns[column_name]
        assert isinstance(column.type, DateTime)
        assert not isinstance(column.type, UtcNaiveDateTime)
        assert column.type.timezone is False
