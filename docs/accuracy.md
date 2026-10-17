# Accuracy & honesty: what is validated vs. what is not

> ⚠️ **This is a proof of concept, not a medical device.** It must not be used
> to make real clinical decisions. The sections below are deliberately precise
> about what the test suite proves and what it does **not**.

## TL;DR

- **Validated:** the safety *logic* — the deterministic rules engine, the
  red-flag escalation, staleness/confidence handling, the server-enforced dose
  caps, config fail-safe, and request-body injection resistance. These are
  covered by the backend test suite and must pass exactly.
- **NOT validated:** the clinical *values* — every pH / temperature / moisture
  threshold and every dose cap is a **placeholder** awaiting literature review
  and clinician sign-off. The logic is correct; the numbers are not clinically
  established.

## Validated — the safety logic (proven by tests)

Each item below maps to tests under `backend/tests/`. The logic is deterministic
(a clock is injected, there is no RNG, no network, no ML), so the same input
always yields the same result.

- **Pure rules engine.** `safety/rules.py::evaluate` is config-only and
  side-effect-free; identical inputs give identical `StatusResult`.
  *(`test_rules_status.py`)*
- **Level ordering & monotonic escalation.** `normal < watch < infection-risk <
  escalate`; combining components can only raise severity.
  *(`test_rules_status.py`)*
- **Flagged values never lower status.** A value flagged `out_of_range` /
  `invalid_timestamp` is excluded from any status-lowering computation.
  *(`test_validation.py`, `test_rules_status.py`)*
- **No usable fresh reading ⇒ `unknown`, never `normal`.** Stale data is not a
  reassuring result. *(`test_staleness.py`, `test_rules_status.py`)*
- **Every red flag is independent, forces escalate, and advises care.** Each of
  the twelve red-flag rules is unit-tested in isolation, including the
  conservative handling of *unknown* risk attributes (surfaced, not assumed
  safe), and messaging always advises — never discourages — seeking care.
  *(`test_red_flags.py`)*
- **Trend direction & sufficiency.** Trends are computed over the configured
  window; too few usable points ⇒ `insufficient_data`, never a false
  "all-clear". *(`test_trends.py`)*
- **Dose caps, deny-closed, from config only.** One test per cap: over-dose,
  over-session, within-min-gap (returns remaining time), daily cap, and
  escalate / active red flag — each denies; a within-limits request grants and
  persists its params. *(`test_dose_caps.py`)*
- **Concurrency safety.** Concurrent dose requests for one wound are serialised
  under a per-wound lock inside a DB transaction, so caps cannot be beaten by a
  race. *(`test_dose_concurrency.py`)*
- **Config fail-safe.** A missing / unparseable safety config makes `/health`
  return `503` and all decision endpoints refuse — no unsafe default.
  *(`test_config_failsafe.py`, `test_api_e2e.py`)*
- **No injected thresholds / caps / status.** Input schemas use
  `extra='forbid'`; a request supplying its own threshold/cap/forced-status is
  rejected and never changes a decision. *(`test_threshold_injection.py`)*
- **Ingestion contract & persistence.** Valid reading ⇒ `201` with a computed
  status; missing field ⇒ `422`; duplicate ⇒ `409` idempotent; datastore
  unavailable ⇒ `5xx` (never a false success). *(`test_api_e2e.py`,
  `test_db_schema.py`)*
- **End-to-end scenario trajectories.** Seeded simulator scenarios driven
  through the real API produce the expected trajectory: `healing → normal`,
  `early_infection → infection-risk`, `heavy_exudate → watch`,
  `inflammation_spike → infection-risk`, `sensor_dropout → reduced confidence`.
  *(`test_e2e_scenarios.py`)*
- **Resilient edge ingestion.** The serial bridge skips a malformed / partial
  line (logged) and continues; a well-formed line is POSTed as a validated
  reading. *(`test_serial_bridge.py`)*
- **Simulated data is flagged.** The simulator marks every reading
  `simulated=True`, verified end-to-end at the source. *(`test_simulator.py`)*

## NOT validated — the clinical values (placeholders)

The following come from `config/clinical_thresholds.yaml` and
`config/safety_limits.yaml`. **Each is tagged `PLACEHOLDER: verify with
literature/clinician` in the YAML and is NOT a clinically established number.**
They were chosen to exercise the logic and make the demo legible, not to be
correct.

| Value | Current placeholder | Status |
| --- | --- | --- |
| pH watch / infection-risk bands | 7.6 / 8.0 | **Placeholder** — not validated |
| Skin-temp watch / infection-risk bands | 34.0 °C / 35.5 °C | **Placeholder** — not validated |
| Moisture watch band | 70 % | **Placeholder** — not validated |
| Freshness window | 1800 s | **Placeholder** — not validated |
| Clock-skew tolerance | 300 s | **Placeholder** — not validated |
| Low-battery threshold | 15 % | **Placeholder** — not validated |
| Trend window | 86 400 s | **Placeholder** — not validated |
| No-improvement horizon (N days) | 5 | **Placeholder** — not validated |
| Max dose | 100 mJ | **Placeholder** — not validated |
| Max session | 120 s | **Placeholder** — not validated |
| Min gap between sessions | 14 400 s (4 h) | **Placeholder** — not validated |
| Max daily sessions | 3 | **Placeholder** — not validated |

Other explicitly out-of-scope / unvalidated aspects:

- **Sensor accuracy & calibration** — not modelled; readings are taken at face
  value aside from plausibility-range flagging.
- **405 nm phototherapy efficacy & safety** — the dose caps bound a *request*;
  they do not assert any therapeutic claim.
- **Clinical outcomes** — no claim is made that any status corresponds to a real
  wound state.

## How to make the values trustworthy later

1. Replace each placeholder in the two YAML files with a literature-backed,
   clinician-reviewed value (keep the `PLACEHOLDER` tag until signed off).
2. Because the engine reads thresholds **only** from config, no code change is
   needed — update the YAML, re-run `python -m pytest backend/tests`, and the
   `config_snapshot` (sha256) recorded on every decision will change to reflect
   the new, reviewed configuration.
