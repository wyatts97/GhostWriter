"""add feed error tracking

Revision ID: 7cb065c7a15a
Revises: 7cb065c7a159
Create Date: 2026-06-09 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7cb065c7a15a"
down_revision: Union[str, None] = "7cb065c7a159"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rss_feeds", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column(
        "rss_feeds",
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rss_feeds", "last_error_at")
    op.drop_column("rss_feeds", "last_error")
