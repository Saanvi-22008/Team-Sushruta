# Requirements — Safety Core and Data Pipeline

## Introduction

This spec covers the P0 backend vertical slice of the Sushruta smart-bandage companion app: the
path from a sensor reading to a safe, deterministic wound status. It deliberately excludes the
frontend, Apollo/LLM, and ML — those are separate specs. The goal is a trustworthy, well-tested
spine that everything else sits on.

In scope:

- The **sensor simulator** with named scenarios (`healing`, `early_infection`, `heavy_exudate`,
  `inflammation_spike`, `sensor_dropout`).
- The **`DataIngestion` interface** and its three sources: `SimulatorSource` (always-available
  fallback), `SerialBridge` (reads one JSON line per reading over USB serial and POSTs to the
  backend), and `HttpDevice` (device POSTs directly over Wi-Fi).
- The **ingestion API** (validate + persist readings).
- The **database schema** (devices, wounds, readings, statuses, dose requests).
- The **deterministic rules engine**: status levels `normal` / `watch` / `infection-risk` /
  `escalate`, red-flag rules, and trend windows.
- The **light-dose request endpoint** with hard caps enforced in the backend.

Out of scope (named here only to set boundaries): React/Vite UI, Apollo retrieval/LLM, ML
anomaly/baseline models, i18n, voice, caregiver view, complementary-care content.

### Guiding non-negotiables (from steering)

- Safety thresholds, red-flag escalation, and dose caps are **deterministic backend code**. No LLM
  or ML can change or bypass them.
- Clinical thresholds live in `config/clinical_thresholds.yaml`, each marked
  `PLACEHOLDER: verify with literature/clinician`. Dose caps live in `config/safety_limits.yaml`.
- Never show stale or simulated data as live; simulated data is labelled `SIMULATED`.
- Never discourage seeking care; red flags always escalate.
- Public repo: no secrets, no real personal data; synthetic/fake demo data only.

### Terminology

- **Reading**: one measurement set from a bandage: `{device_id, wound_id, ts, ph, skin_temp_c,
  moisture_pct, battery_pct, sensor_status}`.
- **Status level** (ordered, least to most severe): `normal` < `watch` < `infection-risk` <
  `escalate`.
- **Red flag**: a condition that forces `escalate` regardless of numeric readings.
- **Stale**: no fresh reading within the configured freshness window.
- **Trend window**: a configured look-back period over which a sustained direction/magnitude of
  change is evaluated.

### Assumptions (stated, continuing per working rules)

- A1: Timestamps (`ts`) are ISO-8601 UTC. Readings may arrive out of order; the backend orders by
  `ts`, not arrival time.
- A2: User risk attributes (diabetic, immunocompromised, wound depth/type, symptom reports such as
  pus/fever/pain) are supplied with the wound record or via a reported-symptoms input; this spec
  consumes them but their capture UI is out of scope. Where absent, rules treat them as "unknown"
  and MUST NOT silently assume the safe-looking value.
- A3: All numeric thresholds and window lengths are config-driven placeholders, not clinically
  validated; the system reports this honestly.
- A4: `405nm` light dosing is modelled as a request + backend decision; no hardware actuation is in
  scope, but the decision and its enforced caps are.

---

## Requirements

### Requirement 1 — Sensor reading data contract and validation

**User story:** As the backend, I want every incoming reading validated against a strict contract,
so that impossible or malformed data is flagged or rejected and never silently trusted.

#### Acceptance criteria

1. WHEN a reading is received THEN the system SHALL require fields `device_id`, `wound_id`, `ts`,
   `ph`, `skin_temp_c`, `moisture_pct`, `battery_pct`, `sensor_status`.
2. IF any required field is missing or has the wrong type THEN the system SHALL reject the reading
   with HTTP 422 and a machine-readable error listing the offending field(s), and SHALL NOT persist
   it as a valid reading.
3. WHEN a numeric field is present but outside its physically plausible range (ranges defined in
   `config/clinical_thresholds.yaml`, e.g. pH 0–14, moisture 0–100%) THEN the system SHALL mark the
   reading `invalid` for that field, persist it flagged (not as clean live data), and SHALL NOT let
   the flagged value drive a *less severe* status.
4. WHEN `sensor_status` is a value other than `ok` / `drifting` / `disconnected` THEN the system
   SHALL treat it as `disconnected` and record a validation warning.
5. WHEN a duplicate reading arrives (same `device_id`, `wound_id`, `ts`) THEN the system SHALL
   deduplicate idempotently and SHALL NOT create a second stored reading.
6. WHEN `ts` is in the future beyond a configured clock-skew tolerance THEN the system SHALL flag
   the reading as `invalid_timestamp` and SHALL NOT treat it as the latest reading.
7. WHEN a reading is persisted THEN the system SHALL record its source (`simulator` / `serial` /
   `http`) and whether it is simulated, so simulated data can never be presented as live/real.

### Requirement 2 — DataIngestion interface and sources

**User story:** As a developer, I want ingestion behind one interface with interchangeable sources,
so the simulator always works as a fallback and real hardware can be swapped in without changing
downstream code.

#### Acceptance criteria

1. The system SHALL define a `DataIngestion` interface that yields validated readings regardless of
   source.
2. The system SHALL provide a `SimulatorSource` that requires no hardware and is always available as
   a fallback.
3. The system SHALL provide a `SerialBridge` that reads one JSON object per line from a USB serial
   port and submits each as a reading to the ingestion API.
4. WHEN the serial stream yields a malformed (non-JSON or partial) line THEN `SerialBridge` SHALL
   skip that line, log a warning, and continue without crashing.
5. The system SHALL provide an `HttpDevice` path where a device POSTs readings directly to the
   ingestion API over the network.
6. WHEN a non-simulator source is unavailable or errors THEN the system SHALL be able to fall back
   to `SimulatorSource` without data from different sources being conflated as the same stream.
7. Readings from every source SHALL pass through the same validation (Requirement 1) before
   persistence.

### Requirement 3 — Sensor simulator with scenarios

**User story:** As a demoer/tester, I want a simulator that produces realistic labelled scenarios,
so the pipeline and rules can be exercised deterministically without hardware.

#### Acceptance criteria

1. The system SHALL support the scenarios `healing`, `early_infection`, `heavy_exudate`,
   `inflammation_spike`, and `sensor_dropout`.
2. WHEN a scenario runs THEN each generated reading SHALL be marked as simulated (per Req 1.7) and
   SHALL conform to the reading contract.
3. WHEN the `sensor_dropout` scenario runs THEN the simulator SHALL produce gaps and/or
   `sensor_status` = `disconnected`/`drifting` so staleness and sensor-health handling can be tested.
4. WHEN run with a fixed seed THEN a scenario SHALL be reproducible (same seed produces the same
   sequence) so tests are deterministic.
5. WHEN `early_infection` or `inflammation_spike` runs for its configured duration THEN the produced
   trajectory SHALL cross the thresholds required to raise status beyond `normal` (so end-to-end
   escalation is demonstrable).

### Requirement 4 — Ingestion API and persistence

**User story:** As the pipeline, I want a clear API to accept readings and persist them, so that
status and history can be derived reliably.

#### Acceptance criteria

1. The system SHALL expose an endpoint to ingest one reading (and MAY accept a batch) that applies
   Requirement 1 validation.
2. WHEN a valid reading is ingested THEN the system SHALL persist it and return a success response
   identifying the stored reading.
3. WHEN ingestion triggers status evaluation THEN the system SHALL run the rules engine
   (Requirement 5) and persist the resulting status with the reading/time it was computed from.
4. The database schema SHALL store devices, wounds, readings, computed statuses, and dose requests,
   with timestamps, source, and simulated flags, and SHALL support querying the latest reading and a
   time-ordered history per wound.
5. WHEN the datastore is unavailable THEN the ingestion endpoint SHALL return a 5xx error and SHALL
   NOT report success.
6. The system SHALL provide a wound status endpoint and a wound timeline/history endpoint
   (consumed later by the UI).

### Requirement 5 — Deterministic rules engine (status levels)

**User story:** As a user relying on safety, I want wound status decided by deterministic,
configurable rules, so results are consistent, testable, and never altered by an LLM or ML.

#### Acceptance criteria

1. The system SHALL compute exactly one status level per evaluation from the ordered set
   `normal` / `watch` / `infection-risk` / `escalate`.
2. The system SHALL load numeric thresholds and trend-window lengths from
   `config/clinical_thresholds.yaml`; the engine SHALL contain no hardcoded clinical numbers.
3. WHEN readings sit within normal ranges with no concerning trend and no red flag THEN the status
   SHALL be `normal`.
4. WHEN a reading or short-term trend crosses a "watch" threshold but not an infection-risk
   threshold, and no red flag applies THEN the status SHALL be `watch`.
5. WHEN readings/trends cross the configured infection-risk thresholds (e.g. sustained rising pH
   plus elevated temperature over the trend window) and no red flag applies THEN the status SHALL be
   `infection-risk`.
6. WHEN multiple conditions apply THEN the system SHALL report the **most severe** applicable level
   (escalation can only raise, never lower, the level).
7. The engine SHALL be a pure function of (readings history + wound/user attributes + config): given
   the same inputs it SHALL always produce the same status, with no network/LLM/ML calls.
8. WHEN status is computed THEN the system SHALL also return a plain-language reason and the specific
   rule(s)/reading(s) that drove it (for display and for honest auditing).
9. The engine SHALL expose/return, alongside the level, a stable machine code and the triggering
   factors so the UI can render colour + icon + plain words (never colour alone) downstream.

### Requirement 6 — Red-flag escalation (always escalates)

**User story:** As an at-risk user, I want any red flag to force escalation, so dangerous cases are
pushed toward a doctor earlier and are never masked by otherwise-normal numbers.

#### Acceptance criteria

1. The system SHALL treat each of the following as a red flag: spreading redness, pus, fever, severe
   pain, rapid worsening, deep/gaping wound, bite/puncture wound, diabetic user, immunocompromised
   user, no improvement over N days (N from config), and sustained abnormal trends.
2. WHEN any single red flag is present THEN the computed status SHALL be `escalate`, regardless of
   how normal the numeric readings look.
3. WHEN status is `escalate` THEN the reason SHALL name which red flag(s) triggered it and SHALL
   advise seeking care; the message SHALL NEVER discourage seeking care.
4. WHEN a user attribute relevant to a red flag is `unknown` (per Assumption A2) THEN the system
   SHALL NOT treat `unknown` as "safe"; it SHALL either treat it conservatively per config or
   surface that the input is missing — never silently downgrade.
5. The system SHALL have a dedicated unit test for every red-flag rule proving it escalates
   (per steering: unit tests for all safety logic).

### Requirement 7 — Trend windows and sustained abnormality

**User story:** As a user, I want gradual, sustained changes detected over time, so slow-building
problems are caught rather than only sudden spikes.

#### Acceptance criteria

1. The system SHALL evaluate trends over configured look-back windows (window length from config).
2. WHEN a metric shows a sustained abnormal direction/magnitude across the trend window (not a
   single noisy sample) THEN the system SHALL raise the status accordingly and MAY register the
   "sustained abnormal trend" red flag per config.
3. WHEN there are too few readings in the window to judge a trend THEN the system SHALL report
   `insufficient_data` for the trend component rather than inferring a false "all clear".
4. Trend evaluation SHALL be deterministic and reproducible for the same reading history.

### Requirement 8 — Staleness and sensor health surfaced, not hidden

**User story:** As a user, I want to know when data is old or a sensor is unhealthy, so I never
trust a stale or simulated value as if it were live.

#### Acceptance criteria

1. WHEN no reading has arrived within the configured freshness window THEN the system SHALL mark the
   wound's data `stale` and SHALL surface it (not hide it or show the old value as current).
2. WHEN the latest reading's `sensor_status` is `drifting` or `disconnected` THEN the system SHALL
   surface sensor health as `drifting`/`disconnected` respectively alongside status.
3. WHEN data is stale or a sensor is `disconnected` THEN the system SHALL NOT present a reassuring
   (`normal`) status as if it were based on current data; it SHALL indicate reduced confidence /
   unknown current state.
4. WHEN a reading is simulated THEN every surface that exposes it SHALL carry the `simulated` flag so
   it can be labelled `SIMULATED` and never shown as live.
5. The system SHALL have unit tests covering stale data, dropped readings, and simulated-vs-live
   labelling.

### Requirement 9 — Light-dose request with hard caps

**User story:** As a user, I want to request a 405nm light session knowing the backend enforces safe
limits, so the dose, session length, and timing can never be exceeded by the UI or Apollo.

#### Acceptance criteria

1. The system SHALL expose a light-dose **request** endpoint; callers (UI, Apollo) can only request,
   never set, dose parameters.
2. The system SHALL load dose caps — maximum dose, maximum session length, and minimum gap between
   sessions — from `config/safety_limits.yaml`, enforced in backend code.
3. WHEN a dose request would exceed the maximum dose or session length THEN the system SHALL deny it
   and return the enforced limit and reason; it SHALL NOT clamp-and-proceed silently unless config
   explicitly defines a clamp behaviour.
4. WHEN a dose request arrives before the minimum gap since the last granted session has elapsed
   THEN the system SHALL deny it and return the time remaining until the next allowed session.
5. WHEN the wound status is `escalate` (or a red flag is active) THEN the system SHALL deny the dose
   request and direct the user toward care, per config.
6. WHEN a dose request is granted THEN the system SHALL persist the granted parameters and timestamp
   so the minimum-gap rule and daily/cumulative caps can be enforced on subsequent requests.
7. No LLM or ML output SHALL be able to alter, bypass, or raise any dose cap; caps are deterministic
   backend code and config only.
8. The system SHALL have unit tests proving each cap (dose, session length, minimum gap, cumulative/
   daily limit, escalate-block) rejects an over-limit request.

### Requirement 10 — Configuration, honesty, and no secrets

**User story:** As a maintainer of a public, safety-sensitive repo, I want all thresholds in
labelled config and the repo free of secrets/real data, so limits are auditable and privacy is
protected.

#### Acceptance criteria

1. `config/clinical_thresholds.yaml` SHALL exist with every clinical value marked
   `PLACEHOLDER: verify with literature/clinician`.
2. `config/safety_limits.yaml` SHALL exist and hold all dose caps.
3. The repository SHALL contain no secrets, API keys, `.env` files, or real personal data; only
   synthetic/clearly-fake demo data (enforced by `.gitignore`/`.kiroignore` already in place).
4. The system SHALL expose or document which values are placeholders vs validated (feeding
   `docs/accuracy.md`), so clinical un-validation is reported honestly.
5. WHEN a safety-relevant config value is missing or unparseable at startup THEN the system SHALL
   fail safe: refuse to serve dose/status decisions that depend on it rather than fall back to an
   unsafe default.

### Requirement 11 — Concurrency safety for dose requests

**User story:** As a user, I want the gap and cumulative caps to hold even if two requests race, so
timing limits cannot be beaten by sending requests simultaneously.

#### Acceptance criteria

1. WHEN two dose requests for the same wound are processed concurrently THEN the system SHALL
   serialize the cap evaluation so that at most one is granted and the other is denied with the gap
   reason.
2. The system SHALL evaluate caps against the committed record of granted sessions, not an
   in-flight/uncommitted value.
3. The system SHALL have a test that fires concurrent dose requests and asserts only the allowed
   number are granted.

### Requirement 12 — Status when usable data is absent or invalid

**User story:** As a user, I want the status to stay honest when the latest data is invalid or
missing, so I am never shown a reassuring status computed from unusable data.

#### Acceptance criteria

1. WHEN the latest reading is flagged invalid for a metric THEN the rules engine SHALL exclude that
   metric's flagged value from any computation that could lower the status, consistent with Req 1.3.
2. WHEN no usable (valid, fresh) reading exists for a wound THEN the system SHALL return a status
   component of `unknown` for the data-driven level (not `normal`) while still applying any active
   red flags (which can still force `escalate`).
3. WHEN `low battery` (below the configured threshold on `battery_pct`) coincides with
   `drifting`/`disconnected` sensor status THEN the system SHALL surface reduced confidence per
   Req 8.3 rather than treating readings as fully reliable.

### Requirement 13 — Auditability of safety decisions

**User story:** As a safety reviewer, I want every status and dose decision recorded with its
inputs and reasons, so decisions are reproducible and honestly auditable.

#### Acceptance criteria

1. WHEN a status is computed THEN the system SHALL persist the level, the machine code, the
   triggering factors, the config version/snapshot used, and the time, linked to the wound.
2. WHEN a dose request is granted OR denied THEN the system SHALL persist the request, the outcome,
   the enforced limit(s) involved, and the reason.
3. The persisted audit records SHALL be sufficient to reproduce why a given decision was made from
   the stored readings and config.

### Requirement 14 — Thresholds come only from config, never from callers

**User story:** As a maintainer, I want thresholds and caps to be unmodifiable via the API, so no
caller (UI, Apollo, ML) can inject or override a safety value.

#### Acceptance criteria

1. The status and dose endpoints SHALL ignore any client-supplied threshold, cap, or status-override
   field; such fields SHALL have no effect on the decision.
2. The rules engine and dose enforcement SHALL read limits only from loaded config, never from
   request payloads.
3. The system SHALL have a test proving that a request attempting to supply its own threshold/cap or
   a forced status does not change the computed decision.

---

## Analysis — gaps reviewed and addressed

A requirements-analysis pass was run against the steering non-negotiables and the stated scope. The
following gaps were found in the first draft (Requirements 1–10) and closed:

- **Concurrency on dose caps** — the minimum-gap/cumulative caps could be beaten by simultaneous
  requests. Added Requirement 11.
- **Status with no usable data** — the rules engine lacked an explicit "no valid/fresh data → not
  `normal`" rule distinct from staleness surfacing. Added Requirement 12 (also pulls `battery_pct`,
  previously unused, into reduced-confidence handling).
- **Auditability** — status persistence existed (Req 4.3) but dose decisions and the config snapshot
  behind a decision were not auditable. Added Requirement 13.
- **Threshold injection** — nothing prevented a caller from supplying its own threshold/cap/override.
  Added Requirement 14 to lock limits to config only (reinforces the "LLM/ML can never change caps"
  non-negotiable at the API boundary).

Known residual boundaries (intentionally out of scope, noted for honesty, not gaps to fix here):

- Clinical correctness of threshold values — these are config placeholders by design (Req 10.1),
  validated against literature/clinician later; tests prove *logic*, not clinical accuracy.
- Authentication/authorization and multi-user data isolation — not required for the P0 demo slice;
  to be addressed before any non-synthetic use.
- Capture UI for user risk attributes and reported symptoms — this spec consumes them (A2); their
  entry UI is a frontend concern.
