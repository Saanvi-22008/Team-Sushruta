from datetime import datetime, timezone
from typing import Any

from backend.schemas import ScenarioRequest


def scenario_payload(scenario: ScenarioRequest) -> dict[str, Any]:
    base: dict[str, Any] = {
        "device_id": "demo-patch-01",
        "wound_id": "demo-wound-01",
        "ts": datetime.now(timezone.utc).isoformat(),
        "ph": 6.8,
        "skin_temp_c": 36.7,
        "moisture_pct": 42,
        "battery_pct": 92,
        "sensor_status": "available",
        "clinical_context": {},
    }
    if scenario.scenario == "early_infection":
        base.update(ph=7.8, skin_temp_c=37.6)
    elif scenario.scenario == "heavy_exudate":
        base.update(moisture_pct=85)
    elif scenario.scenario == "inflammation_spike":
        base.update(skin_temp_c=37.6)
    elif scenario.scenario == "sensor_dropout":
        base.update(
            ph=None,
            skin_temp_c=None,
            moisture_pct=None,
            sensor_status="dropout",
        )
    return base
