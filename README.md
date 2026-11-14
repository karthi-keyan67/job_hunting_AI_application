# AI Job Hunting Agent

A personal job discovery and application preparation workspace. The system is designed to keep the user in control: job approval, application content approval, and submission confirmation are separate steps. Applications are never submitted automatically.

## Phase 1 foundation

This repository currently contains the initial architecture and runtime foundation only. It includes a FastAPI health endpoint, a React/Vite shell, Docker Compose with PostgreSQL, and environment configuration. No job sources, mock listings, authentication, AI calls, or application workflows are implemented yet.

## Run with Docker

1. Copy `.env.example` to `.env` and set a private `POSTGRES_PASSWORD`.
2. Run `docker compose up --build`.
3. Open the UI at <http://localhost:5173> and API health at <http://localhost:8000/api/v1/health>.

PostgreSQL is available on localhost:5432. Compose persists data in the `postgres_data` volume. The API health endpoint reports service liveness; database readiness checks will be added with the database layer.

## Run locally

Backend: from `backend`, create/activate a Python 3.12 environment, install `requirements.txt`, then run `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`.

Frontend: from `frontend`, run `npm install` and `npm run dev -- --host 0.0.0.0`. Set `VITE_API_BASE_URL` if the API is not at `http://localhost:8000/api/v1`.

## Architecture and plan

See [docs/architecture.md](docs/architecture.md), [docs/requirements.md](docs/requirements.md), [docs/database-design.md](docs/database-design.md), [docs/api-specification.md](docs/api-specification.md), and [docs/implementation-plan.md](docs/implementation-plan.md).

## Security baseline

Do not commit `.env`, credentials, resume files, or personal data. External listing and email content will be treated as untrusted input. Connectors must use permitted APIs, feeds, public pages, or user-authorized integrations and must not bypass access controls or anti-bot measures. Application submission remains a user action.
