"""Initial schema: api_keys, jobs, invoices

Revision ID: 001
Revises:
Create Date: 2026-05-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # §5 — api_keys
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("hashed_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer(), server_default="60", nullable=True),
        sa.Column("monthly_cost_cap_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hashed_key"),
    )

    # §5 — jobs
    op.create_table(
        "jobs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("api_key_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("input_source", sa.Text(), nullable=False),
        sa.Column(
            "input_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("output_format", sa.Text(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=True),
        sa.Column("files_completed", sa.Integer(), server_default="0", nullable=True),
        sa.Column("files_failed", sa.Integer(), server_default="0", nullable=True),
        sa.Column("invoices_extracted", sa.Integer(), server_default="0", nullable=True),
        sa.Column("invoices_review", sa.Integer(), server_default="0", nullable=True),
        sa.Column("result_xlsx_key", sa.Text(), nullable=True),
        sa.Column("result_json_key", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 4), server_default="0", nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_jobs_status_created", "jobs", ["status", "created_at"])
    op.create_index("idx_jobs_api_key", "jobs", ["api_key_id"])

    # §5 — invoices
    op.create_table(
        "invoices",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("source_pages", postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column(
            "invoice_index_in_file", sa.Integer(), server_default="1", nullable=True
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=True),
        sa.Column("models_used", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "extracted",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "audit",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_invoices_job", "invoices", ["job_id"])
    op.create_index("idx_invoices_status", "invoices", ["job_id", "status"])


def downgrade() -> None:
    op.drop_index("idx_invoices_status")
    op.drop_index("idx_invoices_job")
    op.drop_table("invoices")
    op.drop_index("idx_jobs_api_key")
    op.drop_index("idx_jobs_status_created")
    op.drop_table("jobs")
    op.drop_table("api_keys")
