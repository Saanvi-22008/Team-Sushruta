"""Seeded simulator source for the Sushruta safety core.

``SimulatorSource(scenario, seed)`` yields ``ReadingIn``-shaped dicts, every one
marked ``simulated=True`` (invariant #10 — simulated data is never shown as
live). A fixed seed reproduces the exact sequence (Req 3.4), which the e2e tests
rely on for deterministic status trajectories.

Five scenarios (trajectories over a trend window, with seeded noise):

- ``healing``           pH drifts toward neutral, temp normal, moisture falling -> stays normal.
- ``early_infection``   pH rises AND temp climbs across the window -> crosses to infection-risk.
- ``heavy_exudate``     moisture high and climbing -> crosses the watch band.
- ``inflammation_spike``temp spike + pH rise -> crosses to infection-risk.
- ``sensor_dropout``    gaps + sensor_status drifting/disconnected -> exercises staleness.

Threshold references (from config/clinical_thresholds.yaml placeholders): the
``early_infection`` / ``inflammation_spike`` trajectories end above
``ph.infection_risk_above`` (8.0) and ``skin_temp_c.infection_risk_above``
(35.5); ``heavy_exudate`` ends above ``moisture_pct.watch_above`` (70). The
simulator hard-codes these end targets so the generated data crosses the bands
regardless of noise; the engine still reads the live thresholds from config.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

SCENARIOS = (
    "healing",
    "early_infection",
    "heavy_exudate",
    "inflammation_spike",
    "sensor_dropout",
)

# Baseline (normal) metric values the trajectories start from.
_BASE_PH = 7.0
_BASE_TEMP = 32.0
_BASE_MOISTURE = 45.0
_BASE_BATTERY = 95.0


class SimulatorSource:
    """A :class:`~app.ingestion.base.DataIngestion` source backed by a scenario.

    Parameters
    ----------
    scenario:
        One of :data:`SCENARIOS`.
    seed:
        RNG seed; a fixed seed reproduces the exact emitted sequence.
    count:
        Number of readings to emit.
    interval_s:
        Nominal spacing between readings (seconds).
    start:
        Timestamp of the first reading (defaults to a fixed epoch so sequences
        are reproducible without an injected clock).
    device_id / wound_id:
        Identity stamped onto every emitted reading.
    """

    source = "simulator"

    def __init__(
        self,
        scenario: str,
        seed: int = 0,
        *,
        count: int = 12,
        interval_s: int = 3600,
        start: datetime | None = None,
        device_id: str = "sim-device-1",
        wound_id: str = "sim-wound-1",
    ) -> None:
        if scenario not in SCENARIOS:
            raise ValueError(
                f"unknown scenario '{scenario}'; expected one of {', '.join(SCENARIOS)}"
            )
        self.scenario = scenario
        self.seed = seed
        self.count = count
        self.interval_s = interval_s
        self.start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.device_id = device_id
        self.wound_id = wound_id

    # -- public API ---------------------------------------------------------

    def readings(self) -> Iterator[dict[str, Any]]:
        """Yield ReadingIn-shaped dicts for the configured scenario."""
        rng = random.Random(self.seed)
        builder = getattr(self, f"_scenario_{self.scenario}")
        yield from builder(rng)

    def generate(self) -> list[dict[str, Any]]:
        """Eagerly materialize the whole sequence (handy for tests)."""
        return list(self.readings())

    # -- helpers ------------------------------------------------------------

    def _ts(self, i: int) -> datetime:
        return self.start + timedelta(seconds=self.interval_s * i)

    def _reading(
        self,
        i: int,
        ph: float,
        skin_temp_c: float,
        moisture_pct: float,
        battery_pct: float,
        sensor_status: str,
    ) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "wound_id": self.wound_id,
            "ts": self._ts(i).isoformat(),
            "ph": round(ph, 3),
            "skin_temp_c": round(skin_temp_c, 3),
            "moisture_pct": round(moisture_pct, 3),
            "battery_pct": round(battery_pct, 3),
            "sensor_status": sensor_status,
            "simulated": True,
        }

    @staticmethod
    def _progress(i: int, n: int) -> float:
        """Fraction 0..1 across the sequence (0 at first reading, 1 at last)."""
        if n <= 1:
            return 1.0
        return i / (n - 1)

    @staticmethod
    def _noise(rng: random.Random, amplitude: float) -> float:
        return rng.uniform(-amplitude, amplitude)

    # -- scenarios ----------------------------------------------------------

    def _scenario_healing(self, rng: random.Random) -> Iterator[dict[str, Any]]:
        n = self.count
        for i in range(n):
            p = self._progress(i, n)
            ph = _BASE_PH - 0.3 * p + self._noise(rng, 0.03)
            temp = _BASE_TEMP - 0.5 * p + self._noise(rng, 0.1)
            moisture = _BASE_MOISTURE - 20.0 * p + self._noise(rng, 0.5)
            battery = _BASE_BATTERY - 2.0 * p + self._noise(rng, 0.2)
            yield self._reading(i, ph, temp, max(0.0, moisture), battery, "ok")

    def _scenario_early_infection(self, rng: random.Random) -> Iterator[dict[str, Any]]:
        n = self.count
        # End targets safely above the infection-risk bands (8.0 pH, 35.5 C).
        ph_end, temp_end = 8.4, 36.5
        for i in range(n):
            p = self._progress(i, n)
            ph = _BASE_PH + (ph_end - _BASE_PH) * p + self._noise(rng, 0.03)
            temp = _BASE_TEMP + (temp_end - _BASE_TEMP) * p + self._noise(rng, 0.08)
            moisture = _BASE_MOISTURE + 10.0 * p + self._noise(rng, 0.5)
            battery = _BASE_BATTERY - 3.0 * p + self._noise(rng, 0.2)
            yield self._reading(i, ph, temp, moisture, battery, "ok")

    def _scenario_heavy_exudate(self, rng: random.Random) -> Iterator[dict[str, Any]]:
        n = self.count
        # End target above moisture watch_above (70); pH/temp stay plausible/normal.
        moisture_end = 85.0
        for i in range(n):
            p = self._progress(i, n)
            ph = _BASE_PH + 0.2 * p + self._noise(rng, 0.03)
            temp = _BASE_TEMP + 0.5 * p + self._noise(rng, 0.08)
            moisture = _BASE_MOISTURE + (moisture_end - _BASE_MOISTURE) * p + self._noise(rng, 0.4)
            battery = _BASE_BATTERY - 2.0 * p + self._noise(rng, 0.2)
            yield self._reading(i, ph, temp, moisture, battery, "ok")

    def _scenario_inflammation_spike(self, rng: random.Random) -> Iterator[dict[str, Any]]:
        n = self.count
        # Flat-ish normal baseline then a sharp spike in the last third that
        # crosses the infection-risk bands (8.0 pH, 35.5 C).
        spike_start = max(1, int(n * 0.66))
        ph_end, temp_end = 8.5, 37.0
        for i in range(n):
            if i < spike_start:
                ph = _BASE_PH + self._noise(rng, 0.03)
                temp = _BASE_TEMP + self._noise(rng, 0.08)
            else:
                # progress within the spike segment
                sp = (i - spike_start + 1) / max(1, (n - spike_start))
                ph = _BASE_PH + (ph_end - _BASE_PH) * sp + self._noise(rng, 0.03)
                temp = _BASE_TEMP + (temp_end - _BASE_TEMP) * sp + self._noise(rng, 0.08)
            moisture = _BASE_MOISTURE + self._noise(rng, 0.5)
            battery = _BASE_BATTERY - 2.0 * self._progress(i, n) + self._noise(rng, 0.2)
            yield self._reading(i, ph, temp, moisture, battery, "ok")

    def _scenario_sensor_dropout(self, rng: random.Random) -> Iterator[dict[str, Any]]:
        n = self.count
        emitted = 0
        for i in range(n):
            # ~1 in 3 slots is a gap: nothing is emitted for that interval.
            if rng.random() < 0.34:
                continue
            # Degrading sensor health: later readings tend to drift/disconnect.
            roll = rng.random()
            p = self._progress(i, n)
            if roll < 0.3 + 0.4 * p:
                status = "disconnected" if roll < 0.15 + 0.3 * p else "drifting"
            else:
                status = "ok"
            ph = _BASE_PH + self._noise(rng, 0.1)
            temp = _BASE_TEMP + self._noise(rng, 0.3)
            moisture = _BASE_MOISTURE + self._noise(rng, 1.0)
            battery = _BASE_BATTERY - 5.0 * p + self._noise(rng, 1.0)
            emitted += 1
            yield self._reading(i, ph, temp, moisture, battery, status)
        # Guarantee the scenario is non-empty even on an unlucky seed.
        if emitted == 0:
            yield self._reading(0, _BASE_PH, _BASE_TEMP, _BASE_MOISTURE, _BASE_BATTERY, "disconnected")
