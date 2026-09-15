"""advisory_page source type (official advisory pages without RSS)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CK = "ck_sources_source_type_valid"
_OLD = "source_type IN ('page', 'group', 'rss', 'google_news', 'weather')"
_NEW = "source_type IN ('page', 'group', 'rss', 'google_news', 'weather', 'advisory_page')"


def upgrade() -> None:
    with op.batch_alter_table("sources") as batch:
        batch.drop_constraint(op.f(_CK), type_="check")
        batch.create_check_constraint(op.f(_CK), _NEW)


def downgrade() -> None:
    op.execute("DELETE FROM posts WHERE source_type = 'advisory_page'")
    op.execute("DELETE FROM sources WHERE source_type = 'advisory_page'")
    with op.batch_alter_table("sources") as batch:
        batch.drop_constraint(op.f(_CK), type_="check")
        batch.create_check_constraint(op.f(_CK), _OLD)
