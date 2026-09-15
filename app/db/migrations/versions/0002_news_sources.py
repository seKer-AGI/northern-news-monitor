"""news/weather sources: new source types and url/locations/hazards on posts

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CK = "ck_sources_source_type_valid"
_OLD = "source_type IN ('page', 'group')"
_NEW = "source_type IN ('page', 'group', 'rss', 'google_news', 'weather')"


def upgrade() -> None:
    with op.batch_alter_table("sources") as batch:
        batch.drop_constraint(op.f(_CK), type_="check")
        batch.create_check_constraint(op.f(_CK), _NEW)

    with op.batch_alter_table("posts") as batch:
        batch.add_column(sa.Column("url", sa.String(length=2048), nullable=True))
        batch.add_column(sa.Column("locations", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("hazards", sa.String(length=500), nullable=True))


def downgrade() -> None:
    news_types = "('rss', 'google_news', 'weather')"
    op.execute(f"DELETE FROM posts WHERE source_type IN {news_types}")
    op.execute(f"DELETE FROM sources WHERE source_type IN {news_types}")

    with op.batch_alter_table("posts") as batch:
        batch.drop_column("hazards")
        batch.drop_column("locations")
        batch.drop_column("url")

    with op.batch_alter_table("sources") as batch:
        batch.drop_constraint(op.f(_CK), type_="check")
        batch.create_check_constraint(op.f(_CK), _OLD)
