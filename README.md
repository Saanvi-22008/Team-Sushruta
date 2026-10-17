# Team-Sushruta — Apollo Safety Core

Apollo is an AI agent for a smart bandage. It reads wound pH, temperature and
moisture, flags infection risk early with a **deterministic** rules engine, and
guides the user — always advising care and escalating to a clinician when red
flags appear.

> ⚠️ **Proof of concept — NOT a medical device.** Nothing here is clinically
> validated. Every clinical threshold and dose cap in `config/` is a
> **placeholder** pending literature review and clinician sign-off, and the
> status output is not medical advice. See [`docs/accuracy.md`](docs/accuracy.md)
> for exactly what is proven (the safety *logic*) versus what is not (the
> clinical *values*). All demo data is synthetic and clearly marked simulated.

## What this is

A P0 vertical slice from a sensor reading to a deterministic wound status:

- A FastAPI backend (`backend/`) with a pure, config-driven rules engine, SQLite
  persistence, HTTP ingestion, and server-enforced dose caps.
- Edge ingestion paths: a serial bridge (`scripts/run_serial_bridge.py`) and a
  direct HTTP device client, plus a seeded simulator demo driver
  (`scripts/run_simulator.py`).
- A React + Vite dashboard (`frontend/`) that renders status as colour **plus**
  icon **plus** plain words, and labels simulated data.

## Prerequisites

- Python 3.11+ (3.13/3.14 wheels are used; see `backend/pyproject.toml`).
- Node 20+ and npm (for the frontend dashboard).

## One-command setup (backend)

Windows PowerShell, from the repo root:

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -e "backend[dev]"
```

macOS / Linux:

```bash
python -m venv backend/.venv
backend/.venv/bin/python -m pip install -e "backend[dev]"
```

Optional: copy the example env (all values are non-secret placeholders):

```bash
cp backend/.env.example backend/.env
```

## Run the backend API

From the `backend/` directory, with the venv active:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

or, without activating the venv (PowerShell, from the repo root):

```powershell
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend
```

- Health check: `GET http://127.0.0.1:8000/health` — returns `200` when the
  safety config loaded, and **`503` fail-safe** when it is missing/unparseable
  (decision endpoints then also refuse, deny-closed).
- **Interactive API docs / OpenAPI spec**: `http://127.0.0.1:8000/docs` and the
  raw spec at `http://127.0.0.1:8000/openapi.json`.

The database URL defaults to `sqlite:///./sushruta.db` (git-ignored) and can be
overridden with the `SUSHRUTA_DB_URL` environment variable.

## Run the demo (seeded simulator)

With the API running (above), drive a synthetic scenario into it from the repo
root:

```bash
python scripts/run_simulator.py --scenario early_infection --seed 1 --post http://127.0.0.1:8000 --interval 1.0
```

Flags:

- `--scenario` — one of `healing`, `early_infection`, `heavy_exudate`,
  `inflammation_spike`, `sensor_dropout`.
- `--seed` — RNG seed for a reproducible run (default `1`).
- `--post` — base URL of the running API (default `http://127.0.0.1:8000`).
- `--interval` — seconds between POSTs for a live feel (`0` = as fast as possible).

Each reading is POSTed through the same validation every source uses; the script
prints the computed status level per reading. The demo data is **synthetic**.

Read the current status or timeline back:

```bash
curl http://127.0.0.1:8000/wounds/sim-wound-1/status
curl http://127.0.0.1:8000/wounds/sim-wound-1/timeline
```

### Serial bridge (optional, real hardware)

A standalone bridge forwards one-JSON-object-per-line readings from a serial
port to the API (malformed lines are skipped and logged; the stream continues):

```bash
python scripts/run_serial_bridge.py --port COM3 --baud 115200 --post http://127.0.0.1:8000
```

## Run the frontend dashboard

```bash
npm --prefix frontend install
npm --prefix frontend run dev     # dev server
npm --prefix frontend run build   # production build
npm --prefix frontend test        # component tests
```

The dashboard reads from the backend API and renders status as colour + icon +
plain words, with a visible SIMULATED label on simulated data.

## Tests

Backend (from the repo root, venv active):

```bash
python -m pytest backend/tests
```

The engine, dose-cap, staleness, config-fail-safe and threshold-injection tests
encode the safety invariants and must pass exactly.

## Safety invariants (enforced in code, proven by tests)

- The rules engine is a **pure** function — config-only, no LLM/ML/network, clock
  injected; same input ⇒ same output.
- Escalation only **raises** status; a lack of usable fresh data is `unknown`,
  never `normal`.
- Dose caps are enforced **server-side from config**, deny-closed, under a
  per-wound lock + DB transaction; request bodies can never inject a
  threshold/cap/status override (`extra='forbid'`).
- A missing/unparseable safety config fails safe: `/health` → `503` and all
  decision endpoints refuse.
- Simulated data is flagged and never shown as live.

See [`docs/accuracy.md`](docs/accuracy.md) for the full validated-vs-placeholder
breakdown.
