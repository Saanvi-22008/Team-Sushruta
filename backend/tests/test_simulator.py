"""Simulator acceptance tests (FEAT-002).

Proves the five scenarios yield contract-valid, always-simulated readings; a
fixed seed reproduces an identical sequence; sensor_dropout produces gaps and/or
drifting/disconnected statuses; and the early_infection / inflammation_spike
trajectories cross the configured thresholds that raise status beyond normal.
"""

from __future__ import annotations

import pytest

from app.core.config import load_config
from app.core.schemas import ReadingIn
from app.ingestion.base import DataIngestion
from app.ingestion.simulator import SCENARIOS, SimulatorSource


@pytest.fixture()
def clinical():
    cfg = load_config()
    assert cfg.loaded, f"config failed to load: {cfg.load_error}"
    return cfg.clinical


def _contract_check(reading: dict) -> ReadingIn:
    # ReadingIn forbids extras, so strip the server-side 'simulated' marker that
    # the simulator stamps onto the dict before contract validation.
    wire = {k: v for k, v in reading.items() if k != "simulated"}
    return ReadingIn(**wire)


def test_simulator_rejects_unknown_scenario():
    with pytest.raises(ValueError):
        SimulatorSource("not-a-scenario", seed=1)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_scenario_yields_contract_valid_and_simulated(scenario):
    src = SimulatorSource(scenario, seed=1)
    readings = src.generate()
    assert len(readings) >= 1
    for r in readings:
        assert r["simulated"] is True
        # Every reading parses against the strict wire contract.
        _contract_check(r)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_fixed_seed_reproduces_identical_sequence(scenario):
    a = SimulatorSource(scenario, seed=42).generate()
    b = SimulatorSource(scenario, seed=42).generate()
    assert a == b


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_different_seed_changes_sequence(scenario):
    a = SimulatorSource(scenario, seed=1).generate()
    b = SimulatorSource(scenario, seed=2).generate()
    # At least one differs; scenarios have seeded noise so sequences diverge.
    assert a != b


def test_simulator_satisfies_dataingestion_protocol():
    src = SimulatorSource("healing", seed=1)
    assert isinstance(src, DataIngestion)
    assert src.source == "simulator"


def test_sensor_dropout_has_gaps_or_degraded_status():
    src = SimulatorSource("sensor_dropout", seed=3, count=12, interval_s=3600)
    readings = src.generate()
    # Gaps: fewer emitted than requested count, OR missing time slots.
    had_gap = len(readings) < 12
    statuses = {r["sensor_status"] for r in readings}
    degraded = bool(statuses & {"drifting", "disconnected"})
    assert had_gap or degraded


def test_healing_stays_within_normal_bands(clinical):
    readings = SimulatorSource("healing", seed=1).generate()
    last = readings[-1]
    assert last["ph"] <= clinical.ph_watch_above
    assert last["skin_temp_c"] <= clinical.skin_temp_c_watch_above
    assert last["moisture_pct"] <= clinical.moisture_pct_watch_above


def test_early_infection_crosses_infection_risk(clinical):
    readings = SimulatorSource("early_infection", seed=1).generate()
    last = readings[-1]
    # Final trajectory crosses BOTH infection-risk bands.
    assert last["ph"] > clinical.ph_infection_risk_above
    assert last["skin_temp_c"] > clinical.skin_temp_c_infection_risk_above


def test_inflammation_spike_crosses_infection_risk(clinical):
    readings = SimulatorSource("inflammation_spike", seed=1).generate()
    last = readings[-1]
    assert last["ph"] > clinical.ph_infection_risk_above
    assert last["skin_temp_c"] > clinical.skin_temp_c_infection_risk_above


def test_heavy_exudate_crosses_moisture_watch(clinical):
    readings = SimulatorSource("heavy_exudate", seed=1).generate()
    last = readings[-1]
    assert last["moisture_pct"] > clinical.moisture_pct_watch_above


def test_all_scenario_values_within_plausible_ranges(clinical):
    # Simulated readings must be plausible (not out_of_range) so validation
    # flags them clean — otherwise they could never drive a status.
    for scenario in SCENARIOS:
        for r in SimulatorSource(scenario, seed=5).generate():
            assert clinical.plausible_ph.min <= r["ph"] <= clinical.plausible_ph.max
            assert (
                clinical.plausible_skin_temp_c.min
                <= r["skin_temp_c"]
                <= clinical.plausible_skin_temp_c.max
            )
            assert 0.0 <= r["moisture_pct"] <= 100.0
            assert 0.0 <= r["battery_pct"] <= 100.0
