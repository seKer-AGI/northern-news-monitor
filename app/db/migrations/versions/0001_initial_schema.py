"""initial schema: sources, posts, collection_runs, collection_errors

Revision ID: 0001
Revises:
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_identifier", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('page', 'group')", name=op.f("ck_sources_source_type_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        sa.UniqueConstraint(
            "source_type", "source_identifier", name=op.f("uq_sources_type_identifier")
        ),
    )

    op.create_table(
        "collection_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("sources_processed", sa.Integer(), nullable=False),
        sa.Column("posts_found", sa.Integer(), nullable=False),
        sa.Column("posts_saved", sa.Integer(), nullable=False),
        sa.Column("posts_skipped", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'partial_success', 'failed')",
            name=op.f("ck_collection_runs_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_runs")),
    )
    op.create_index(
        op.f("ix_collection_runs_started_at"), "collection_runs", ["started_at"], unique=False
    )
    op.create_index(op.f("ix_collection_runs_status"), "collection_runs", ["status"], unique=False)

    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("external_post_id", sa.String(length=255), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_posts_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_posts")),
        sa.UniqueConstraint(
            "source_id", "external_post_id", name=op.f("uq_posts_source_external_post")
        ),
    )
    op.create_index(op.f("ix_posts_posted_at"), "posts", ["posted_at"], unique=False)
    op.create_index(op.f("ix_posts_source_id"), "posts", ["source_id"], unique=False)

    op.create_table(
        "collection_errors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("source_name", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["collection_runs.id"],
            name=op.f("fk_collection_errors_run_id_collection_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_collection_errors_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_errors")),
    )
    op.create_index(
        op.f("ix_collection_errors_run_id"), "collection_errors", ["run_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_collection_errors_run_id"), table_name="collection_errors")
    op.drop_table("collection_errors")
    op.drop_index(op.f("ix_posts_source_id"), table_name="posts")
    op.drop_index(op.f("ix_posts_posted_at"), table_name="posts")
    op.drop_table("posts")
    op.drop_index(op.f("ix_collection_runs_status"), table_name="collection_runs")
    op.drop_index(op.f("ix_collection_runs_started_at"), table_name="collection_runs")
    op.drop_table("collection_runs")
    op.drop_table("sources")
