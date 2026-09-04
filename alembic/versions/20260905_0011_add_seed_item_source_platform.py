"""add source platform to seed items

Revision ID: 20260905_0011
Revises: 20260904_0010
Create Date: 2026-09-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260905_0011"
down_revision = "20260904_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fapai_seed_item",
        sa.Column("source_platform", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_fapai_seed_item_source_platform",
        "fapai_seed_item",
        ["source_platform"],
        unique=False,
    )
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            sa.text(
                "UPDATE fapai_seed_item "
                "SET source_platform = LEFT(NULLIF(source_payload ->> 'source_platform', ''), 32) "
                "WHERE source_platform IS NULL AND source_payload IS NOT NULL"
            )
        )
    elif dialect == "sqlite":
        op.execute(
            sa.text(
                "UPDATE fapai_seed_item "
                "SET source_platform = substr(NULLIF(json_extract(source_payload, '$.source_platform'), ''), 1, 32) "
                "WHERE source_platform IS NULL AND source_payload IS NOT NULL "
                "AND json_valid(source_payload)"
            )
        )


def downgrade() -> None:
    op.drop_index("ix_fapai_seed_item_source_platform", table_name="fapai_seed_item")
    op.drop_column("fapai_seed_item", "source_platform")
