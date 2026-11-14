# AI Job Hunting Agent

A personal job discovery and application preparation workspace. Job review, application-content approval, and manual submission confirmation are separate checkpoints. Applications are never submitted automatically.

## Current scope: Phases 1–4

The repository includes a FastAPI API, React/Vite workspace, PostgreSQL persistence, password authentication with rotating/revocable refresh tokens, authenticated profile/preferences APIs, private resume storage and versioning, and a job source/ingestion workspace. Phase 4 supports configured public career pages, user-authorized Gmail alert parsing when OAuth is configured, unsupported portal status reporting, and manual job imports. AI matching and application workflows are not implemented.

## Run with Docker

1. Copy `.env.example` to `.env`; set a strong private `POSTGRES_PASSWORD` and `JWT_SECRET`.
2. Run `docker compose up --build -d`.
3. Apply the schema: `docker compose exec backend python -m alembic upgrade head`.
4. Open the UI at <http://localhost:5173>, health at <http://localhost:8000/api/v1/health>, and API docs at <http://localhost:8000/docs>.

PostgreSQL is exposed on localhost:5433 and persists in the `postgres_data` volume. This avoids the common conflict with a PostgreSQL service already bound to 5432. Compose does not run migrations automatically. The API health endpoint checks database connectivity.

## Run locally

Backend: from `backend`, create a Python 3.12+ environment, install `requirements.txt`, start PostgreSQL, then run `python -m alembic upgrade head` and `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`. Settings load `.env` from the repository root. Configure `DATABASE_URL` or the `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, and `POSTGRES_PORT` components. The host port in `.env.example` is 5433; Compose connects to PostgreSQL inside its network on port 5432.

Frontend: from `frontend`, run `npm install` and `npm run dev -- --host 0.0.0.0`. Set `VITE_API_BASE_URL` if needed.

## Environment and tests

Important settings: optional `DATABASE_URL` override (async SQLAlchemy URL), PostgreSQL connection components, `JWT_SECRET` (use a long random secret outside development), `ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS`, `CORS_ORIGINS`, `RESUME_STORAGE_ROOT`, and `MAX_RESUME_UPLOAD_BYTES`. `.env.example` lists all settings. Tests use `TEST_DATABASE_URL` or the separate `VERIFY_DATABASE_NAME` database; PostgreSQL is required.

Passwords are hashed with Argon2id through `pwdlib` when the native Argon2 provider is available, with a scrypt fallback for environments that block that provider. The stored value is always a one-way hash. Refresh JWTs are stored only as SHA-256 digests.

From `backend`, install development dependencies with `python -m pip install -r requirements-dev.txt`, set `TEST_DATABASE_URL` to a dedicated PostgreSQL test database, then run `python -m pytest -q`. The suite migrates that isolated test database and downgrades it after the session. In Docker, use `docker compose --profile verification run --rm backend-test`; the verification profile targets `VERIFY_DATABASE_NAME`, never the application database. Migration commands: `python -m alembic upgrade head`, `python -m alembic current`, and (disposable database only) `python -m alembic downgrade base`.

## Authentication and profile examples

Register and use the returned bearer token:

```powershell
$body = @{ email = 'you@example.com'; password = 'use-a-long-unique-password' } | ConvertTo-Json
$tokens = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth/register -ContentType 'application/json' -Body $body
$headers = @{ Authorization = "Bearer $($tokens.access_token)" }
Invoke-RestMethod -Uri http://localhost:8000/api/v1/auth/me -Headers $headers
```

Read/update profile:

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/v1/profile -Headers $headers
$profile = @{ full_name = 'Your Name'; current_designation = 'Developer'; currency = 'INR' } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri http://localhost:8000/api/v1/profile -Headers $headers -ContentType 'application/json' -Body $profile
```

The profile update includes full name, designation, company, experience months, notice days, salary range, currency, and bio. `PUT /api/v1/preferences` updates target roles, required/optional skills, experience/salary ranges, locations, work modes, excluded companies, and active status. Refresh through `POST /api/v1/auth/refresh`; logout through `POST /api/v1/auth/logout` with an access bearer token and refresh-token body.

## Resume workspace

Authenticated users can upload PDF and DOCX documents (5 MB default limit), browse and add versions, select a default resume, download original files, preview extracted text, and delete resumes or non-final versions. Files live in the private `resume_data` Docker volume and are never served as static assets. Parsing is local text extraction only; scanned PDFs are marked `NEEDS_OCR` because OCR is not in scope. See `docs/api-specification.md` for endpoint details.

PowerShell upload example (after registration/login):

```powershell
$headers = @{ Authorization = "Bearer $($tokens.access_token)" }
curl.exe -H "Authorization: Bearer $($tokens.access_token)" -F "file=@resume.pdf" -F "title=Backend resume" http://localhost:8000/api/v1/resumes
Invoke-RestMethod -Uri http://localhost:8000/api/v1/resumes -Headers $headers
```

## Job sources and collection

The authenticated UI at <http://localhost:5173> supports adding and managing sources, testing and manually running a configured connector, reviewing run history, filtering collected jobs, and importing a job URL by hand. Public career pages require a public HTTP(S) URL and CSS selectors in source configuration; robots.txt and bounded request limits are enforced. The import form stores the URL and submitted listing fields without fetching it. Job data and source records are scoped to the owning account.

Gmail alert ingestion requires explicit OAuth setup and sender allowlisting; it is fail-closed until configured. Job portals such as LinkedIn, Naukri, Indeed, and others are marked unsupported until an authorized API/feed or user-authorized integration is available. No CAPTCHA bypass, authenticated scraping, recurring scheduler, matching, or application submission is included. See [docs/api-specification.md](docs/api-specification.md) for endpoints and connector limitations.

After editing a source, use **Test** to validate its configuration and access, then **Collect** to execute one bounded run. Collection is intentionally one-shot; `python -m app.worker` from `backend` does not install a recurring schedule.

## Architecture and plan

See [docs/architecture.md](docs/architecture.md), [docs/requirements.md](docs/requirements.md), [docs/database-design.md](docs/database-design.md), [docs/api-specification.md](docs/api-specification.md), and [docs/implementation-plan.md](docs/implementation-plan.md).

## Security baseline

Do not commit `.env`, credentials, resume files, or personal data. External listing and email content will be treated as untrusted input. Connectors must use permitted APIs, feeds, public pages, or user-authorized integrations and must not bypass access controls or anti-bot measures. Application submission remains a user action.
