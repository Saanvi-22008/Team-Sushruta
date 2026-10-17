"""Config fail-safe acceptance tests (FEAT-001).

Proves the safety invariant that a missing/unparseable safety config never
produces a usable default, and that the sha256 snapshot is stable.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import (
    DEFAULT_CLINICAL_PATH,
    DEFAULT_SAFETY_PATH,
    ClinicalThresholds,
    DoseLimits,
    load_config,
)


def test_good_config_loads_into_dataclasses() -> None:
    cfg = load_config()
    assert cfg.loaded
    assert cfg.load_error is None
    assert isinstance(cfg.clinical, ClinicalThresholds)
    assert isinstance(cfg.dose, DoseLimits)
    # Values come through from the YAML.
    assert cfg.clinical.plausible_ph.max == 14.0
    assert cfg.clinical.unknown_attr_policy == "conservative"
    assert cfg.dose.clamp is False
    assert cfg.dose.block_on_escalate is True
    assert cfg.config_snapshot is not None
    assert cfg.config_snapshot.startswith("sha256:")


def test_frozen_dataclass_is_immutable() -> None:
    cfg = load_config()
    try:
        cfg.dose.max_dose_mj = 9999  # type: ignore[misc]
    except Exception as exc:  # frozen dataclass raises FrozenInstanceError
        assert "cannot assign" in str(exc).lower() or "frozen" in str(exc).lower()
    else:  # pragma: no cover - must not reach here
        raise AssertionError("DoseLimits should be immutable")


def test_missing_file_sets_load_error_no_raise(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.yaml"
    cfg = load_config(clinical_path=missing, safety_path=DEFAULT_SAFETY_PATH)
    # No raise; fail-safe flag set; no usable thresholds; no snapshot.
    assert cfg.loaded is False
    assert cfg.load_error is not None
    assert "missing" in cfg.load_error.lower()
    assert cfg.clinical is None
    assert cfg.dose is None
    assert cfg.config_snapshot is None


def test_garbled_file_sets_load_error_no_raise(tmp_path: Path) -> None:
    garbled = tmp_path / "garbled.yaml"
    garbled.write_text("this: : : not valid yaml ][", encoding="utf-8")
    cfg = load_config(clinical_path=garbled, safety_path=DEFAULT_SAFETY_PATH)
    assert cfg.loaded is False
    assert cfg.load_error is not None
    assert cfg.clinical is None
    assert cfg.dose is None
    assert cfg.config_snapshot is None


def test_structurally_invalid_sets_load_error(tmp_path: Path) -> None:
    # Parses as YAML mapping but missing required keys => fail safe, no default.
    partial = tmp_path / "partial.yaml"
    partial.write_text("plausible: {}\n", encoding="utf-8")
    cfg = load_config(clinical_path=partial, safety_path=DEFAULT_SAFETY_PATH)
    assert cfg.loaded is False
    assert cfg.clinical is None
    assert cfg.dose is None


def test_snapshot_identical_across_two_loads() -> None:
    first = load_config(DEFAULT_CLINICAL_PATH, DEFAULT_SAFETY_PATH)
    second = load_config(DEFAULT_CLINICAL_PATH, DEFAULT_SAFETY_PATH)
    assert first.config_snapshot == second.config_snapshot


def test_snapshot_identical_for_identical_input(tmp_path: Path) -> None:
    clinical_src = DEFAULT_CLINICAL_PATH.read_text(encoding="utf-8")
    safety_src = DEFAULT_SAFETY_PATH.read_text(encoding="utf-8")
    a_clin = tmp_path / "a_clin.yaml"
    a_safe = tmp_path / "a_safe.yaml"
    b_clin = tmp_path / "b_clin.yaml"
    b_safe = tmp_path / "b_safe.yaml"
    for p, src in ((a_clin, clinical_src), (b_clin, clinical_src)):
        p.write_text(src, encoding="utf-8")
    for p, src in ((a_safe, safety_src), (b_safe, safety_src)):
        p.write_text(src, encoding="utf-8")
    cfg_a = load_config(a_clin, a_safe)
    cfg_b = load_config(b_clin, b_safe)
    assert cfg_a.config_snapshot == cfg_b.config_snapshot
