"""Plain helper functions shared by the FEAT-004 API tests.

Kept out of ``conftest.py`` so they can be imported directly (there are two
conftest modules on the path; ``import conftest`` resolves to the backend-level
one, so test-only helpers live here instead).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.models_db import Device, Wound


def seed_wound(
    session_factory,
    wound_id: str = "wound-1",
    device_id: str = "dev-1",
    *,
    attr_diabetic=False,
    attr_immunocompromised=False,
    depth_type="superficial",
):
    """Insert a device + wound so FK-bearing rows and attrs are available.

    Attributes default to explicit known-safe values so a test can isolate the
    data-driven status/dose behaviour; pass ``None`` to exercise the
    conservative unknown-attribute escalation (invariant #5).
    """
    s = session_factory()
    try:
        if s.get(Device, device_id) is None:
            s.add(Device(device_id=device_id))
        if s.get(Wound, wound_id) is None:
            s.add(
                Wound(
                    wound_id=wound_id,
                    device_id=device_id,
                    attr_diabetic=attr_diabetic,
                    attr_immunocompromised=attr_immunocompromised,
                    depth_type=depth_type,
                )
            )
        s.commit()
    finally:
        s.close()


def reading_payload(
    *,
    device_id: str = "dev-1",
    wound_id: str = "wound-1",
    ts: datetime | None = None,
    ph: float = 7.0,
    skin_temp_c: float = 32.0,
    moisture_pct: float = 45.0,
    battery_pct: float = 95.0,
    sensor_status: str = "ok",
) -> dict:
    if ts is None:
        ts = datetime.now(timezone.utc)
    return {
        "device_id": device_id,
        "wound_id": wound_id,
        "ts": ts.isoformat(),
        "ph": ph,
        "skin_temp_c": skin_temp_c,
        "moisture_pct": moisture_pct,
        "battery_pct": battery_pct,
        "sensor_status": sensor_status,
    }
