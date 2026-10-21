"""Add the TinyFish activity log and the guidance cache."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_apollo_tables"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tinyfish_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("topic", sa.String(length=48), nullable=False),
        sa.Column("query_text", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("detail", sa.String(length=200), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
    )
    op.create_index("ix_tinyfish_calls_ts", "tinyfish_calls", ["ts"], unique=False)
    op.create_table(
        "guidance_cache",
        sa.Column("topic", sa.String(length=48), primary_key=True),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("guidance_cache")
    op.drop_index("ix_tinyfish_calls_ts", table_name="tinyfish_calls")
    op.drop_table("tinyfish_calls")
