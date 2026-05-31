"""add source_json_path to property_audit

Revision ID: 20260512_0002
Revises: 20260511_0001
Create Date: 2026-05-12 18:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260512_0002"
down_revision = "20260511_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("property_audit", sa.Column("source_json_path", sa.Text(), nullable=True))

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            UPDATE property_audit AS pa
            SET source_json_path = src.source_file
            FROM (
                SELECT DISTINCT ON (item_id)
                    item_id,
                    event_payload ->> 'source_file' AS source_file
                FROM property_ingest_event
                WHERE item_id IS NOT NULL
                  AND event_payload IS NOT NULL
                  AND COALESCE(event_payload ->> 'source_file', '') <> ''
                ORDER BY item_id, id DESC
            ) AS src
            WHERE pa.item_id = src.item_id
              AND COALESCE(pa.source_json_path, '') = ''
            """
        )


def downgrade() -> None:
    op.drop_column("property_audit", "source_json_path")
