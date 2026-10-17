"""Domain validation for incoming readings.

Two concerns kept deliberately separate (per design.md):

1. **Contract** — required fields present and the right type. A missing or
   wrong-type field is REJECTED (``ContractError`` lists the offending fields);
   it is never persisted as a valid reading.
2. **Plausibility / honesty flagging** — a schema-valid reading is checked
   against the config plausible ranges and clock-skew tolerance. An implausible
   value is NOT silently trusted and NOT dropped: it is persisted with an
   ``out_of_range`` / ``invalid_timestamp`` flag in ``field_flags`` so the rules
   engine can exclude it from any computation that would LOWER status
   (safety invariant #3). Flagging never raises.

The validator also normalizes ``sensor_status`` (an unknown value becomes
``disconnected`` plus a warning), builds the ``dedup_key``
(``device_id|wound_id|ts``), and stamps ``source`` + ``simulated`` so the
simulated flag is preserved end-to-end (invariant #10).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from app.core.config import ClinicalThresholds, Range

# Field-flag values.
FLAG_OK = "ok"
FLAG_OUT_OF_RANGE = "out_of_range"
FLAG_INVALID_TIMESTAMP = "invalid_timestamp"

VALID_SENSOR_STATUS = {"ok", "drifting", "disconnected"}

# Required wire fields and their accepted python types (after JSON decode).
_REQUIRED_FIELDS: dict[str, tuple[type, ...]] = {
    "device_id": (str,),
    "wound_id": (str,),
    "ts": (str, datetime),
    "ph": (int, float),
    "skin_temp_c": (int, float),
    "moisture_pct": (int, float),
    "battery_pct": (int, float),
    "sensor_status": (str,),
}

# Numeric metrics mapped to their plausible-range attribute on the config.
_PLAUSIBLE_METRICS: dict[str, str] = {
    "ph": "plausible_ph",
    "skin_temp_c": "plausible_skin_temp_c",
    "moisture_pct": "plausible_moisture_pct",
    "battery_pct": "plausible_battery_pct",
}


class ContractError(ValueError):
    """Raised when required fields are missing or the wrong type.

    ``fields`` names every offending field so the API can return them in a 422.
    """

    def __init__(self, fields: list[str], detail: str) -> None:
        self.fields = fields
        super().__init__(detail)


@dataclass
class ValidatedReading:
    """A reading that passed the contract and carries plausibility flags.

    ``field_flags`` is per-field (ok | out_of_range | invalid_timestamp).
    ``warnings`` collects non-fatal normalizations (e.g. unknown sensor_status).
    """

    device_id: str
    wound_id: str
    ts: datetime
    ph: float
    skin_temp_c: float
    moisture_pct: float
    battery_pct: float
    sensor_status: str
    source: str
    simulated: bool
    field_flags: dict[str, str] = field(default_factory=dict)
    dedup_key: str = ""
    warnings: list[str] = field(default_factory=list)

    def has_usable(self, metric: str) -> bool:
        """True when ``metric`` is not flagged, i.e. safe for lowering status."""
        return self.field_flags.get(metric, FLAG_OK) == FLAG_OK


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value)
        # Accept trailing 'Z' (ISO-8601 UTC) which fromisoformat rejects pre-3.11
        # style; normalize to +00:00 for robustness.
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _check_contract(payload: Mapping[str, Any]) -> list[str]:
    """Return the list of offending field names (missing or wrong type)."""
    offending: list[str] = []
    for name, types in _REQUIRED_FIELDS.items():
        if name not in payload or payload[name] is None:
            offending.append(name)
            continue
        value = payload[name]
        # bool is a subclass of int; reject it where a number is required.
        if types == (int, float) and isinstance(value, bool):
            offending.append(name)
            continue
        if not isinstance(value, types):
            offending.append(name)
    return offending


def _flag_range(metric: str, value: float, rng: Range) -> str:
    if value < rng.min or value > rng.max:
        return FLAG_OUT_OF_RANGE
    return FLAG_OK


def validate_reading(
    payload: Mapping[str, Any],
    config: ClinicalThresholds,
    *,
    source: str,
    simulated: bool,
    now: Optional[datetime] = None,
) -> ValidatedReading:
    """Validate one reading payload.

    Raises :class:`ContractError` on missing/wrong-type fields. Otherwise returns
    a :class:`ValidatedReading` with plausibility ``field_flags`` set — flagged
    values are preserved (not trusted, not silently used to lower status).

    ``now`` is injected (defaults to current UTC) so timestamp-skew checks are
    deterministic in tests.
    """
    offending = _check_contract(payload)
    if offending:
        raise ContractError(
            sorted(offending),
            f"missing or wrong-type field(s): {', '.join(sorted(offending))}",
        )

    now = now or datetime.now(timezone.utc)
    try:
        ts = _parse_ts(payload["ts"])
    except (ValueError, TypeError) as exc:
        raise ContractError(["ts"], f"unparseable timestamp: {exc}") from exc

    ph = float(payload["ph"])
    skin_temp_c = float(payload["skin_temp_c"])
    moisture_pct = float(payload["moisture_pct"])
    battery_pct = float(payload["battery_pct"])

    flags: dict[str, str] = {}
    numeric = {
        "ph": ph,
        "skin_temp_c": skin_temp_c,
        "moisture_pct": moisture_pct,
        "battery_pct": battery_pct,
    }
    for metric, value in numeric.items():
        rng: Range = getattr(config, _PLAUSIBLE_METRICS[metric])
        flags[metric] = _flag_range(metric, value, rng)

    # Future timestamp beyond the configured clock-skew tolerance -> flagged.
    warnings: list[str] = []
    skew = (ts - now).total_seconds()
    if skew > config.clock_skew_tolerance_s:
        flags["ts"] = FLAG_INVALID_TIMESTAMP
    else:
        flags["ts"] = FLAG_OK

    # Normalize sensor_status; unknown -> disconnected + warning (never trusted).
    raw_status = str(payload["sensor_status"]).strip().lower()
    if raw_status in VALID_SENSOR_STATUS:
        sensor_status = raw_status
    else:
        sensor_status = "disconnected"
        warnings.append(
            f"unknown sensor_status '{payload['sensor_status']}' -> disconnected"
        )

    device_id = str(payload["device_id"])
    wound_id = str(payload["wound_id"])
    dedup_key = f"{device_id}|{wound_id}|{ts.isoformat()}"

    return ValidatedReading(
        device_id=device_id,
        wound_id=wound_id,
        ts=ts,
        ph=ph,
        skin_temp_c=skin_temp_c,
        moisture_pct=moisture_pct,
        battery_pct=battery_pct,
        sensor_status=sensor_status,
        source=source,
        simulated=simulated,
        field_flags=flags,
        dedup_key=dedup_key,
        warnings=warnings,
    )
