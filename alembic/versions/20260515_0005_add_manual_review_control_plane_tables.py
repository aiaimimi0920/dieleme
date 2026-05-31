"""add manual review control plane tables

Revision ID: 20260515_0005
Revises: 20260512_0004
Create Date: 2026-05-15 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260515_0005"
down_revision = "20260512_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manual_review_receipt",
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("ready_signal", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("receipt_updated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("action", "ready_signal"),
    )
    op.create_index("ix_manual_review_receipt_status", "manual_review_receipt", ["status"], unique=False)
    op.create_index("ix_manual_review_receipt_receipt_updated_at", "manual_review_receipt", ["receipt_updated_at"], unique=False)

    op.create_table(
        "manual_review_receipt_job",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("receipt_action", sa.String(length=128), nullable=False),
        sa.Column("receipt_ready_signal", sa.String(length=128), nullable=False),
        sa.Column("maintenance_options", sa.JSON(), nullable=True),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("ix_manual_review_receipt_job_status", "manual_review_receipt_job", ["status"], unique=False)
    op.create_index("ix_manual_review_receipt_job_receipt_action", "manual_review_receipt_job", ["receipt_action"], unique=False)
    op.create_index("ix_manual_review_receipt_job_receipt_ready_signal", "manual_review_receipt_job", ["receipt_ready_signal"], unique=False)
    op.create_index("ix_manual_review_receipt_job_started_at", "manual_review_receipt_job", ["started_at"], unique=False)
    op.create_index("ix_manual_review_receipt_job_finished_at", "manual_review_receipt_job", ["finished_at"], unique=False)

    op.create_table(
        "manual_review_receipt_operation",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("operation_id", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("ready_signal", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("payload_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("execution_mode", sa.String(length=32), nullable=False),
        sa.Column("maintenance_job_id", sa.String(length=64), nullable=True),
        sa.Column("deleted", sa.Boolean(), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_manual_review_receipt_operation_operation_id", "manual_review_receipt_operation", ["operation_id"], unique=True)
    op.create_index("ix_manual_review_receipt_operation_operation", "manual_review_receipt_operation", ["operation"], unique=False)
    op.create_index("ix_manual_review_receipt_operation_action", "manual_review_receipt_operation", ["action"], unique=False)
    op.create_index("ix_manual_review_receipt_operation_ready_signal", "manual_review_receipt_operation", ["ready_signal"], unique=False)
    op.create_index("ix_manual_review_receipt_operation_execution_mode", "manual_review_receipt_operation", ["execution_mode"], unique=False)
    op.create_index("ix_manual_review_receipt_operation_maintenance_job_id", "manual_review_receipt_operation", ["maintenance_job_id"], unique=False)
    op.create_index("ix_manual_review_receipt_operation_requested_at", "manual_review_receipt_operation", ["requested_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_manual_review_receipt_operation_requested_at", table_name="manual_review_receipt_operation")
    op.drop_index("ix_manual_review_receipt_operation_maintenance_job_id", table_name="manual_review_receipt_operation")
    op.drop_index("ix_manual_review_receipt_operation_execution_mode", table_name="manual_review_receipt_operation")
    op.drop_index("ix_manual_review_receipt_operation_ready_signal", table_name="manual_review_receipt_operation")
    op.drop_index("ix_manual_review_receipt_operation_action", table_name="manual_review_receipt_operation")
    op.drop_index("ix_manual_review_receipt_operation_operation", table_name="manual_review_receipt_operation")
    op.drop_index("ix_manual_review_receipt_operation_operation_id", table_name="manual_review_receipt_operation")
    op.drop_table("manual_review_receipt_operation")

    op.drop_index("ix_manual_review_receipt_job_finished_at", table_name="manual_review_receipt_job")
    op.drop_index("ix_manual_review_receipt_job_started_at", table_name="manual_review_receipt_job")
    op.drop_index("ix_manual_review_receipt_job_receipt_ready_signal", table_name="manual_review_receipt_job")
    op.drop_index("ix_manual_review_receipt_job_receipt_action", table_name="manual_review_receipt_job")
    op.drop_index("ix_manual_review_receipt_job_status", table_name="manual_review_receipt_job")
    op.drop_table("manual_review_receipt_job")

    op.drop_index("ix_manual_review_receipt_receipt_updated_at", table_name="manual_review_receipt")
    op.drop_index("ix_manual_review_receipt_status", table_name="manual_review_receipt")
    op.drop_table("manual_review_receipt")
