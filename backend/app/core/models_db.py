"""SQLAlchemy 2.x declarative models for the Sushruta safety core.

Schema follows design.md. Clinical attributes that can be ``unknown`` are
nullable (NULL == unknown, never silently assumed). The ``readings`` table
enforces ``UNIQUE(dedup_key)`` so a duplicate device/wound/ts is rejected at the
database level (idempotent ingestion).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "devices"

    device_id: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    wounds: Mapped[list["Wound"]] = relationship(back_populates="device")


class Wound(Base):
    __tablename__ = "wounds"

    wound_id: Mapped[str] = mapped_column(String, primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.device_id"), nullable=False)
    body_site: Mapped[str | None] = mapped_column(String, nullable=True)
    depth_type: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # Nullable => unknown; never defaulted to a safe-looking value.
    attr_diabetic: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    attr_immunocompromised: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    device: Mapped["Device"] = relationship(back_populates="wounds")
    reported_symptoms: Mapped[list["ReportedSymptom"]] = relationship(back_populates="wound")


class ReportedSymptom(Base):
    __tablename__ = "reported_symptoms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wound_id: Mapped[str] = mapped_column(ForeignKey("wounds.wound_id"), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    wound: Mapped["Wound"] = relationship(back_populates="reported_symptoms")


class Reading(Base):
    __tablename__ = "readings"
    __table_args__ = (UniqueConstraint("dedup_key", name="uq_readings_dedup_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String, nullable=False)
    wound_id: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ph: Mapped[float | None] = mapped_column(Float, nullable=True)
    skin_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    moisture_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    battery_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sensor_status: Mapped[str] = mapped_column(String, nullable=False)
    # Server-added persist fields.
    source: Mapped[str] = mapped_column(String, nullable=False)  # simulator|serial|http
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    field_flags: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    dedup_key: Mapped[str] = mapped_column(String, nullable=False)  # device_id|wound_id|ts


class Status(Base):
    __tablename__ = "statuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wound_id: Mapped[str] = mapped_column(String, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    from_reading_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level: Mapped[str] = mapped_column(String, nullable=False)
    machine_code: Mapped[str | None] = mapped_column(String, nullable=True)
    data_level: Mapped[str | None] = mapped_column(String, nullable=True)
    sensor_health: Mapped[str | None] = mapped_column(String, nullable=True)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    factors: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reason_text: Mapped[str | None] = mapped_column(String, nullable=True)
    config_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)


class DoseRequest(Base):
    __tablename__ = "dose_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wound_id: Mapped[str] = mapped_column(String, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    requested_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    outcome: Mapped[str] = mapped_column(String, nullable=False)  # granted|denied
    enforced_limits: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    granted_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    config_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # status|dose
    wound_id: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
