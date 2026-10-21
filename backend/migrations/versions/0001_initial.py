"""Create the simulated wound reading table."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "readings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.String(length=80), nullable=False),
        sa.Column("wound_id", sa.String(length=80), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ph", sa.Float(), nullable=True),
        sa.Column("skin_temp_c", sa.Float(), nullable=True),
        sa.Column("moisture_pct", sa.Float(), nullable=True),
        sa.Column("battery_pct", sa.Integer(), nullable=False),
        sa.Column("sensor_status", sa.String(length=20), nullable=False),
        sa.Column("clinical_context", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=48), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("device_id", "ts", name="uq_readings_device_timestamp"),
    )
    op.create_index(
        "ix_readings_wound_timestamp", "readings", ["wound_id", "ts"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_readings_wound_timestamp", table_name="readings")
    op.drop_table("readings")
