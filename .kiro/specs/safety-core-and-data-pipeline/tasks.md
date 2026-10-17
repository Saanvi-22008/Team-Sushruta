# Tasks — Safety Core and Data Pipeline

Small, ordered tasks. Each lists the tests that prove it works. Build in order; run tests after each.
Requirement references point back to `requirements.md`.

- [ ] 1. Project scaffold and config loader (fail-safe)
  - Create `backend/` package, `pyproject.toml`/`requirements.txt` (fastapi, uvicorn, sqlalchemy,
    pydantic v2, pyyaml, pytest, httpx, pyserial), `.env.example`.
  - Create `config/clinical_thresholds.yaml` and `config/safety_limits.yaml` with PLACEHOLDER tags.
  - Implement `core/config.py`: load+validate YAML into immutable dataclasses, compute sha256
    snapshot, fail-safe when missing/unparseable.
  - _Tests:_ `test_config_failsafe.py` — loads good config; missing/garbled file → load error flag;
    snapshot is stable for same input. _Reqs: 10.1, 10.2, 10.5._

- [ ] 2. Database schema and session
  - Implement `core/models_db.py` (devices, wounds, reported_symptoms, readings, statuses,
    dose_requests, audit_log) and `core/db.py` (engine, WAL, create-all, session dep).
  - _Tests:_ create tables in-memory; insert/query a reading; UNIQUE(dedup_key) rejects duplicate.
    _Reqs: 4.4, 1.5._

- [ ] 3. Wire contract + validation
  - Implement `core/schemas.py` (`ReadingIn` with `additionalProperties:false`) and
    `ingestion/validator.py`: required-field/type check, plausibility flagging, sensor_status
    normalization, future-ts flag, dedup key, source/simulated stamping.
  - _Tests:_ `test_validation.py` — missing field→reject; wrong type→reject; out-of-range→flagged
    not trusted; bad sensor_status→disconnected+warn; duplicate→dedup; future ts→invalid_timestamp;
    simulated flag preserved. _Reqs: 1.1–1.7._

- [ ] 4. DataIngestion interface + SimulatorSource + scenarios
  - Implement `ingestion/base.py` (interface) and `ingestion/simulator.py` with the five scenarios,
    seeded RNG.
  - _Tests:_ `test_simulator.py` — each scenario yields contract-valid simulated readings; fixed
    seed reproducible; dropout produces gaps/disconnected; early_infection/inflammation_spike
    trajectories cross thresholds. _Reqs: 2.1, 2.2, 3.1–3.5._

- [ ] 5. Trend windows
  - Implement `safety/trends.py`: direction/magnitude over `trend_window_s`; `insufficient_data`
    when too few points; deterministic.
  - _Tests:_ `test_trends.py` — sustained rise detected; single spike not treated as sustained;
    too-few-points→insufficient_data; same history→same result. _Reqs: 7.1–7.4._

- [ ] 6. Red-flag rules (one test each)
  - Implement `safety/red_flags.py`: spreading redness, pus, fever, severe pain, rapid worsening,
    deep/gaping, bite/puncture, diabetic, immunocompromised, no-improvement-N-days, sustained
    abnormal trend. Conservative handling of `unknown` attributes.
  - _Tests:_ `test_red_flags.py` — a dedicated test per red flag asserting it forces escalate;
    unknown attr not downgraded. _Reqs: 6.1–6.5, 12 (unknown handling)._

- [ ] 7. Staleness + sensor health + confidence
  - Implement `safety/staleness.py`: freshness window, sensor health passthrough, reduced-confidence
    when stale/drifting/disconnected or low-battery+drift; never present stale as fresh `normal`.
  - _Tests:_ `test_staleness.py` — stale→surfaced+reduced confidence; disconnected→not reassuring
    normal; simulated labelled; low battery + drift → reduced. _Reqs: 8.1–8.5, 12.3._

- [ ] 8. Deterministic rules engine (status levels)
  - Implement `safety/rules.py` `evaluate(...)` combining usable-reading selection, trends, red
    flags, staleness → one level + machine_code + factors + reason + confidence. Pure; config-only;
    no usable data → `unknown` not `normal`; most-severe wins.
  - _Tests:_ `test_rules_status.py` — normal/watch/infection-risk cases from config; most-severe
    combination; flagged value can't lower status; no-usable-data→unknown; same input→same output.
    _Reqs: 5.1–5.9, 12.1, 12.2._

- [ ] 9. Audit records
  - Implement `safety/audit.py` + persistence of status decisions with config snapshot.
  - _Tests:_ status decision persists level/code/factors/snapshot; reproducible from stored data.
    _Reqs: 13.1, 13.3._

- [ ] 10. Ingestion API + status/timeline endpoints
  - Implement `api/readings.py` (POST /readings, /readings/batch), `api/status.py`
    (GET status, GET timeline), DI wiring in `main.py`, `/health` with config fail-safe.
  - On ingest: validate → persist → evaluate → persist status → audit → return.
  - _Tests:_ `test_api_e2e.py` — valid reading→201 with status; missing field→422; duplicate→409;
    DB-down→5xx; config-missing→503 health; status+timeline endpoints return ordered data.
    _Reqs: 4.1–4.6, 1.2, 10.5._

- [ ] 11. Light-dose request endpoint + hard caps
  - Implement `safety/dose.py` (deny-closed checks) and `api/dose.py`
    (POST /wounds/{id}/dose-requests), per-wound lock + transaction, persist grants, audit.
  - _Tests:_ `test_dose_caps.py` — one test per cap: over-dose denied, over-session denied,
    within-gap denied (returns remaining), daily cap denied, escalate/red-flag blocks; grant
    persists params+timestamp. `test_dose_concurrency.py` — concurrent requests → only allowed
    number granted. _Reqs: 9.1–9.8, 11.1–11.3, 13.2._

- [ ] 12. Threshold-injection lock
  - Confirm `additionalProperties:false` + server-only config reads; add explicit test.
  - _Tests:_ `test_threshold_injection.py` — request supplying its own threshold/cap/forced status
    does not change the decision. _Reqs: 14.1–14.3._

- [ ] 13. Serial bridge + HTTP device paths
  - Implement `ingestion/serial_bridge.py` (reads one JSON line/reading, skips malformed lines,
    POSTs), `scripts/run_serial_bridge.py`, and document `HttpDevice` POST path (`http_device.py`).
  - _Tests:_ serial parser skips malformed line and continues; well-formed line → ReadingIn posted
    (mock transport). _Reqs: 2.3–2.7._

- [ ] 14. Demo driver script + end-to-end scenario proof
  - `scripts/run_simulator.py --scenario ... --post ...` to feed the API live for the demo.
  - _Tests:_ e2e: run each scenario through the API; assert trajectory
    (healing→normal, early_infection→infection-risk, heavy_exudate→watch, dropout→stale/reduced).
    _Reqs: 3.5, 8, 5._

- [ ] 15. Minimal live-status dashboard (demo-able vertical slice)
  - React + Vite app under `frontend/` reading `/wounds/{id}/status` + `/timeline`, rendering the
    reference design's identity: status = colour + icon + plain words, values with units +
    last-updated + sensor health, SIMULATED label, dose-request button (request only), Apollo
    placeholder, emergency button. Base ≥18px, 48px targets, visible focus, APP_NAME constant,
    i18n-ready strings (no hardcoded copy).
  - _Tests:_ component test that status renders colour+icon+words (not colour alone) and SIMULATED
    label shows for simulated data; build succeeds. _Reqs: steering accessibility; 8.4._

- [ ] 16. Docs: README + accuracy honesty
  - Update `README.md`: one-command setup, run instructions, API docs pointer (`/openapi.json`),
    demo script, "proof of concept, not a medical device" disclaimer. Create `docs/accuracy.md`
    stating what is validated (logic via tests) vs NOT (clinical values are placeholders).
  - _Tests:_ n/a (docs); verify demo script commands run as written. _Reqs: 10.4, steering working
    rules._
