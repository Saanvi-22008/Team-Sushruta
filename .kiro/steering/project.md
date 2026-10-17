---

inclusion: always

---

# Sushruta health care app (working name) + Apollo AI agent

Repo: https://github.com/Saanvi-22008/Team-Sushruta. Smart-bandage companion app for a hackathon (AzinHack). The bandage senses wound pH, skin temperature and moisture and can deliver dose-limited 405nm violet light. The app shows the data, explains it, and includes Apollo, an AI wound-care assistant. This is a proof of concept and decision-support software, NOT a medical device. A working demo-able vertical slice beats breadth.

The app name is "Sushruta" (the reference design file spells it "shusuta"). Keep the name in ONE config constant (APP_NAME) and the i18n files, never hardcoded, so the spelling can change later.

Users: injured people, elderly users, caregivers. Assume low tech comfort, poor eyesight, shaky hands, stress, slow networks, English and Hindi speakers.

## Non-negotiables (priority order)

1. SAFETY

- Apollo never diagnoses. It explains data and guides.

- Alert thresholds, red-flag escalation and light-dose limits are DETERMINISTIC BACKEND CODE. An LLM or ML model can never change or bypass them.

- Dose caps (dose, session length, minimum gap) are enforced in the backend from config/safety_limits.yaml. The UI and Apollo can only REQUEST a dose.

- Clinical thresholds live in config/clinical_thresholds.yaml, each marked "PLACEHOLDER: verify with literature/clinician".

- Red flags always escalate: spreading redness, pus, fever, severe pain, rapid worsening, deep/gaping wound, bite/puncture, diabetic or immunocompromised user, no improvement over N days, sustained abnormal trends.

- Goal: get risky cases to a doctor EARLIER and spare unnecessary visits for minor ones. Never discourage seeking care.

- Traditional/Ayurvedic content: separate labelled "complementary" tab, off for red-flag/diabetic/immunocompromised/deep-wound users, never advise applying anything under the smart bandage or ingesting remedies, each item has an evidence tag and source.

2. ACCURACY

- Show values with units, a "last updated" time and sensor health (ok / drifting / disconnected). Never show stale or simulated data as live. Label simulated data SIMULATED.

- Apollo answers only from the curated knowledge base (markdown files in knowledge/, each with a cited source) plus current wound state. It cites sources and says "I'm not sure, please consult a doctor" when unsure. It never invents medical facts or numbers. No web scraping.

- Unit tests for all safety logic (every red-flag rule, attempts to exceed dose caps, stale data). Maintain evals/apollo_eval.yaml with a runner and report pass rates honestly.

- Maintain docs/accuracy.md: what is validated, how, and what is NOT (ML on synthetic data proves logic, not clinical accuracy).

3. ACCESSIBILITY (WCAG 2.2 AA, elderly-first)

- Base text >= 18px with 3 user-selectable sizes remembered; contrast >= 4.5:1 (7:1 for key status text); touch targets >= 48px.

- Never colour alone: status = colour + icon + plain words ("All good", "Keep watching", "See a doctor today").

- One primary action per screen, plain language (reading age ~12), no dense tables on the main screen.

- Keyboard + screen-reader support, visible focus, reduced-motion respected.

- Voice input and read-aloud in Apollo chat (Web Speech API, graceful fallback).

- Persistent emergency button (number configurable, default 112) and an easy caregiver/family share view.

- i18n from day one: English + Hindi, no hardcoded strings.

- Works on low-end phones and slow networks; loading and offline states handled.

- Look: calm, soft, warm, light by default (no dark-only theme). Legibility beats decoration.

4. PRIVACY AND PUBLIC REPO

- The repository is PUBLIC. Never commit secrets, API keys, .env files, real personal data, phone numbers or emails. Use .env + .env.example. Only synthetic or clearly fake demo data in the repo.

- Health data is sensitive: consent screen, data minimisation, no personal identifiers in LLM prompts.

## Architecture

device or simulator -> ingestion API -> database -> rules engine (safety) -> Apollo (retrieval + LLM + ML) -> app UI

- Ingestion is an interface (DataIngestion) with three sources: SimulatorSource (always available as fallback), SerialBridge (microcontroller prints one JSON line per reading over USB serial; a small Python script reads it and POSTs to the backend; this is the demo default) and HttpDevice (the device POSTs directly over Wi-Fi). BLE is optional, after P0.

- Reading contract: {device_id, wound_id, ts, ph, skin_temp_c, moisture_pct, battery_pct, sensor_status}. Validate ranges, reject or flag impossible values, handle missing/noisy/duplicate readings.

- Stack defaults: Python backend (Flask or FastAPI) + SQLite; React + Vite frontend; scikit-learn; LLM behind a provider-agnostic wrapper with the key in an env var. Ask before adding heavy dependencies.

- ML: per-wound adaptive baseline + anomaly/trend model trained on clearly labelled SYNTHETIC data, feedback loop, retrain with versioning and rollback. ML adjusts sensitivity only, never safety limits.

- Simulator scenarios: healing, early_infection, heavy_exudate, inflammation_spike, sensor_dropout.

- Reference design: design/reference/shusuta_health_care_dashboard.html. Keep its identity but substantially improve UX and accessibility.

## Priorities

P0 (must demo): simulator + serial bridge -> ingest -> rules -> live-status dashboard -> Apollo chat with citations and escalation.

P1: ML personalization + retrain demo, voice, Hindi, caregiver view, eval report.

P2: complementary-care tab, polish.

Do not start P1 or P2 until P0 works end to end.

## Working rules

- Small tasks; run tests and show results after each.

- Feature branches (feat/<name>), clear commits. Never commit to main, never force-push, never run destructive git commands, and never push without asking me.

- Keep README current: one-command setup, run instructions, API docs, demo script, and a clear "proof of concept, not a medical device" disclaimer.

- State assumptions when ambiguous and continue.
