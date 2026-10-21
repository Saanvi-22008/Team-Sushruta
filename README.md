# Sushruta — Phase 1

Sushruta is a Hindi- and English-friendly companion for a future smart wound patch. This phase demonstrates a simulated reading dashboard and a deterministic safety status for patients, caregivers, and clinicians. It is a proof of concept, not a medical device, and it does not diagnose or replace care from a clinician.

## What works in this phase

- Expo Go mobile app with a first-launch Hindi/English choice, remembered language, and three remembered text sizes.
- Home screen with simulated pH, skin temperature, moisture, patch battery, status explanations, and read-aloud.
- Built-in simulator scenarios for expected readings, elevated pH, high moisture, a temperature change, and sensor dropout.
- FastAPI ingestion endpoint, PostgreSQL storage through SQLAlchemy, Alembic migration, and deterministic safety rules.
- Tests for the safety escalation rules, status bands, sensor dropout, and impossible readings.

All clinical values are placeholders. The simulator is not connected to hardware, and no reading is clinical evidence.

## Stack

| Area | Technology |
| --- | --- |
| Mobile | Expo, React Native, TypeScript, Expo Router |
| API | Python 3.11, FastAPI, Pydantic, HTTPX |
| Data | PostgreSQL, SQLAlchemy, Alembic |
| Tests | pytest |
| Container demo | Docker Compose |

## Replit development

The mobile workflow runs the Expo app. The API workflow runs FastAPI. The Replit PostgreSQL `DATABASE_URL` must be available.

```sh
.pythonlibs/bin/alembic upgrade head
pnpm --filter @workspace/api-server run dev
pnpm --filter @workspace/sushruta run typecheck
```

The API starts its simulated readings through the same `POST /api/readings` route used for ingestion.

## Docker demo

Docker is not available inside Replit's app runtime. These Docker files are intended for a machine with Docker Engine and Compose installed; they have not been verified inside Replit.

```sh
cp .env.example .env
docker compose up --build
```

The API listens on `http://localhost:8080`. Compose starts PostgreSQL, waits for its health check, applies the Alembic migration, and runs FastAPI. The `.env` file is ignored by Git.

## API endpoints

- `GET /api/healthz` — health check
- `POST /api/readings` — validate, classify, and save a reading
- `GET /api/readings/latest` — latest reading and safety status
- `GET /api/status` — current safety status
- `POST /api/simulator/scenario` — create a simulated reading via the ingestion route

## Tests

```sh
.pythonlibs/bin/pytest -q
```

## Safety and language review

- `config/clinical_thresholds.json` contains placeholder ranges that need clinician review.
- `docs/accuracy.md` explains what the tests do and do not prove.
- `docs/hindi-review.md` lists prewritten safety copy for fluent-reader review.

## Not included yet

Apollo live guidance, TinyFish and Docker sponsor attribution, speech-to-text, document scanning, guarded light sessions, Care, trends, and the remaining settings are deferred to the later phases in the build brief.
