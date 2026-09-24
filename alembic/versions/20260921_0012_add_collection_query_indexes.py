"""Add collection query indexes without rewriting or removing stored records."""
from alembic import op

revision = "20260921_0012"
down_revision = "20260905_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_fapai_seed_item_status_first_seen", "fapai_seed_item", ["status", "first_seen_at"])
    op.create_index("ix_property_ingest_event_type_created", "property_ingest_event", ["event_type", "created_at"])


def downgrade() -> None:
    # Only the indexes introduced here are removed; event and item rows are retained.
    op.drop_index("ix_property_ingest_event_type_created", table_name="property_ingest_event")
    op.drop_index("ix_fapai_seed_item_status_first_seen", table_name="fapai_seed_item")
