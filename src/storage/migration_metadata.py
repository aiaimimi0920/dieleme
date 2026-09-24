"""Alembic metadata for ORM tables and the migration-owned PostGIS column."""
from sqlalchemy import Column, Index, MetaData, text
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.types import UserDefinedType

from .models import Base


class Geography(UserDefinedType):
    cache_ok = True

    def __init__(self, geometry_type="Point", srid=4326):
        self.geometry_type = str(geometry_type).upper()
        self.srid = int(srid)

    def get_col_spec(self, **kwargs):
        return f"geography({self.geometry_type},{self.srid})"


def metadata_for_dialect(dialect_name):
    if dialect_name != "postgresql":
        return Base.metadata
    # Revision 0001 adds this raw-SQL spatial projection, outside the ORM.
    ischema_names.setdefault("geography", Geography)
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(metadata)
    listing = metadata.tables["property_listing"]
    listing.append_column(Column("geom", Geography(), nullable=True))
    Index("idx_property_listing_geom", listing.c.geom, postgresql_using="gist")
    return metadata


def extension_table_filter(connection):
    """Exclude only tables actually owned by an installed PostgreSQL extension."""
    if connection.dialect.name != "postgresql":
        return lambda obj, name, type_, reflected, compare_to: True
    extension_tables = set(connection.execute(text("""
        SELECT c.relname FROM pg_class c
        JOIN pg_depend d ON d.objid = c.oid AND d.classid = 'pg_class'::regclass
        JOIN pg_extension e ON e.oid = d.refobjid
        WHERE d.deptype = 'e' AND c.relkind IN ('r', 'p')
          AND pg_table_is_visible(c.oid)
    """)).scalars())

    def include_object(obj, name, type_, reflected, compare_to):
        return not (type_ == "table" and reflected and name in extension_tables)

    return include_object
