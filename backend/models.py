from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class ReadingRecord(Base):
    __tablename__ = "readings"
    __table_args__ = (
        UniqueConstraint("device_id", "ts", name="uq_readings_device_timestamp"),
        Index("ix_readings_wound_timestamp", "wound_id", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(80), nullable=False)
    wound_id: Mapped[str] = mapped_column(String(80), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ph: Mapped[float | None] = mapped_column(Float, nullable=True)
    skin_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    moisture_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    battery_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    sensor_status: Mapped[str] = mapped_column(String(20), nullable=False)
    clinical_context: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(48), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
