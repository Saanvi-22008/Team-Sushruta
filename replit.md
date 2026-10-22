# Sushruta

A Hindi- and English-friendly wound-care companion prototype that displays simulated wound-patch readings and deterministic safety guidance.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — apply the development migration and run the FastAPI server
- `pnpm --filter @workspace/sushruta run dev` — run the Expo mobile app
- `.pythonlibs/bin/pytest -q` — run backend safety tests
- `.pythonlibs/bin/alembic upgrade head` — apply the development PostgreSQL schema
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- Required env: `DATABASE_URL` — PostgreSQL connection string supplied by Replit
- Optional secrets: `TINYFISH_API_KEY` (live Apollo guidance)

## Stack

- Mobile: Expo Go, React Native, TypeScript, Expo Router
- API: Python 3.11, FastAPI, Pydantic, HTTPX
- DB: PostgreSQL, SQLAlchemy, Alembic
- API codegen: Orval, from `lib/api-spec/openapi.yaml`
- Container demo: Docker Compose

## Where things live

- `artifacts/sushruta/` — Expo mobile app
- `backend/` — FastAPI routes, data models, safety logic, and simulator
- `backend/migrations/` — Alembic migrations
- `config/clinical_thresholds.json` — placeholder safety thresholds
- `lib/api-spec/openapi.yaml` — API contract and generated client source

## Architecture decisions

- Readings are marked `SIMULATED`; no live patch is connected.
- Deterministic safety rules are authoritative and do not use an LLM.
- Clinical ranges are placeholders and require clinician review.
- The FastAPI service reuses the existing `/api` service route.

## Product

History tab shows stored readings plus an experimental, advisory Trend watch (ml/). Apollo can also run a TinyFish browser agent (Find care nearby). Apollo (chat tab) answers from TinyFish-fetched trusted sites; red-flag rules and the patch status escalate before any AI text. TinyFish and Docker logos appear in the Apollo header. Phase 1 includes a simulated readings Home screen with Hindi/English text, adjustable text size, read-aloud, and safety status. Later phases in the project brief cover Apollo, care tools, documents, and light-session requests.

## User preferences

Follow the phase order in the project brief and stop after each completed phase.

## Gotchas

- Do not present placeholder thresholds as clinically validated.
- Docker files are for a machine with Docker installed; Replit's app runtime does not run Docker.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
