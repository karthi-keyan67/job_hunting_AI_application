# AI Job Hunting Agent

A personal job discovery and application preparation workspace. Job review, application-content approval, and manual submission confirmation are separate checkpoints. Applications are never submitted automatically.

## Current scope: Phases 1–8

The repository includes a FastAPI API, React/Vite workspace, PostgreSQL persistence, password authentication with rotating/revocable refresh tokens, authenticated profile/preferences APIs, private resume storage and versioning, authorized job-source ingestion, explainable job matching, job reviews, versioned application drafts, human approval checklists, manual submission handoff, audit history, a user-scoped job-search dashboard, application pipeline, interview and follow-up tracking, and database-backed analytics. AI prepares content only; users review and approve exact versions and submit applications themselves.

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

Important settings: optional `DATABASE_URL` override (async SQLAlchemy URL), PostgreSQL connection components, `JWT_SECRET` (use a long random secret outside development), `ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS`, `CORS_ORIGINS`, `RESUME_STORAGE_ROOT`, `MAX_RESUME_UPLOAD_BYTES`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `MATCHING_AI_ENABLED`, `MATCHING_WEIGHTS`, `APPLICATION_GENERATION_DAILY_LIMIT`, and `APPLICATION_GENERATION_TIMEOUT_SECONDS`. AI features are disabled unless configured. Matching weights default to skills 40%, experience 20%, role 15%, location/work mode 15%, and salary 10%; they must be JSON with exactly those keys and total 100. `.env.example` lists all settings. Tests use `TEST_DATABASE_URL` or the separate `VERIFY_DATABASE_NAME` database; PostgreSQL is required.

Passwords are hashed with Argon2id through `pwdlib` when the native Argon2 provider is available, with a scrypt fallback for environments that block that provider. The stored value is always a one-way hash. Refresh JWTs are stored only as SHA-256 digests.

From `backend`, install development dependencies with `python -m pip install -r requirements-dev.txt`, set `TEST_DATABASE_URL` to a dedicated PostgreSQL test database, then run `python -m pytest -q`. Tests migrate the isolated schema to head and clean test-owned rows afterward; they preserve the database and schema. In Docker, use `docker compose --profile verification run --rm backend-test`; the verification profile targets `VERIFY_DATABASE_NAME`, never the application database. Migration commands: `python -m alembic upgrade head` and `python -m alembic current`.

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

The profile update includes full name, designation, company, experience months, notice days, salary range, currency, and bio. `PUT /api/v1/preferences` updates target roles, required/optional skills, experience/salary ranges, locations, work modes, excluded companies/roles, employment types, and active status. Refresh through `POST /api/v1/auth/refresh`; logout through `POST /api/v1/auth/logout` with an access bearer token and refresh-token body.

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

Gmail alert ingestion requires explicit OAuth setup and sender allowlisting; it is fail-closed until configured. Job portals such as LinkedIn, Naukri, Indeed, and others are marked unsupported until an authorized API/feed or user-authorized integration is available. No CAPTCHA bypass, authenticated scraping, or automated application submission is included. See [docs/api-specification.md](docs/api-specification.md) for endpoints and connector limitations.

After editing a source, use **Test** to validate its configuration and access, then **Collect** to execute one bounded run. The Automation section also supports a user-triggered run and displays collection history.

## Phase 8 automation and notifications

The dedicated `worker` Compose service runs separately from FastAPI. It holds a PostgreSQL advisory lock and schedules collection at 00:00, 06:00, 12:00, and 18:00 in `AUTOMATION_TIMEZONE` (default `Asia/Kolkata`). It uses existing enabled, user-owned, configured sources, Phase 4 collection, and Phase 5 cached matching. Gmail stays fail-closed without OAuth. No application is submitted automatically.

Apply additive migrations before starting the worker or backend against an upgraded database:

```powershell
docker compose -p job-hunting-agent-p2verify --env-file .env exec backend python -m alembic upgrade head
docker compose -p job-hunting-agent-p2verify --env-file .env up -d worker
docker compose -p job-hunting-agent-p2verify --env-file .env ps
```

Use `AUTOMATION_TIMEZONE`, `COLLECTION_TIMEOUT_SECONDS`, and `COLLECTION_RETRY_ATTEMPTS` for the scheduler and collection limits. Email delivery is off by default. To enable it, configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_EMAIL`, optional `SMTP_USERNAME` / `SMTP_PASSWORD`, and `SMTP_STARTTLS`; each user must also opt in under notification preferences. The outbox retains delivery state and retries provider failures with backoff. In-app notification records remain available without an email provider.

The dashboard's **Automation** section shows worker heartbeat, next run, per-source collection and matching metrics, run history, the notification inbox, and preference controls. Authenticated APIs are documented in [docs/api-specification.md](docs/api-specification.md). User-owned operational records, outbox state, scheduled executions, and worker heartbeat are documented in [docs/database-design.md](docs/database-design.md).

## Phase 9 security and deployment verification

Login failures are rate-limited per hashed client/email fingerprint using PostgreSQL state. Configure `AUTH_LOGIN_MAX_ATTEMPTS` and `AUTH_LOGIN_WINDOW_MINUTES`. `APP_ENV=production` rejects the development JWT secret, default database password, non-HTTPS or wildcard CORS origins, and incomplete SMTP credentials. Production mode also disables interactive OpenAPI documentation. These checks improve startup safety but do not make the development Compose/Vite stack production-ready. Review [docs/security-review.md](docs/security-review.md), [docs/deployment-guide.md](docs/deployment-guide.md), [docs/testing-guide.md](docs/testing-guide.md), and [docs/known-limitations.md](docs/known-limitations.md) before deployment.

The Phase 9 PostgreSQL verification result and migration revision are recorded in [docs/implementation-plan.md](docs/implementation-plan.md). Never run destructive migration verification against the application database or its volume; use a newly created disposable database and retain it unless it is separately approved for deletion.

Run full PostgreSQL backend tests against the dedicated verification database and frontend checks with:

```powershell
docker compose -p job-hunting-agent-p2verify --env-file .env --profile verification run --rm backend-test
cd frontend
npm test
npm run build
```

## Job matching

The **Job matches** workspace lets you choose a parsed resume version, run matching for all owned active jobs or selected jobs, rematch, filter and sort results, and inspect job details, skills, score confidence, missing criteria, strengths, concerns, and optional AI evidence. A deterministic score is always available without OpenAI credentials.

The score is the weighted average of criteria with enough data: `sum(criterion_score × configured_weight) / sum(available criterion weights)`. Confidence is the sum of available configured weights as a percentage. Required skills count twice as much as preferred skills within the skills score. Missing salary/experience does not become zero. Deterministic exclusions and known preference conflicts remain visible as `MISMATCH`; AI cannot override them or approve/apply to a job.

To enable AI, set `OPENAI_API_KEY` on the backend and `MATCHING_AI_ENABLED=true`. The API sends a bounded resume summary without contact fields, and job descriptions are treated as untrusted data. Structured AI output and exact evidence quotes are validated; one retry is allowed for transient failures, and deterministic output is kept if AI is unavailable. Identical input versions are cached in match history, with model/prompt/scoring versions and token counts recorded.

Matching endpoints are under `/api/v1/matching`: `POST /run`, `POST /jobs/{job_id}`, `POST /rematch`, `GET /results`, `GET /results/{match_id}`, and `GET /summary`. See [docs/api-specification.md](docs/api-specification.md) for filters and request fields.

## Job review and application preparation

The **Application workflow** uses matching results to approve preparation, save, or reject jobs. Approving only permits draft preparation. AI can prepare a tailored resume, cover letter, recruiter message, and suggested answers using selected resume facts and job details. Draft versions are retained; edits and regeneration create new versions. Contact details are withheld from the provider, unknown salary/notice/work-authorization questions remain marked `[USER INPUT REQUIRED]`, and provider citations are checked against supplied resume/job context. Review every draft and approve the exact versions before completing the mandatory checklist.

Final approval records the user, checklist snapshot, and exact approved draft IDs. It unlocks an HTTPS handoff to the original application URL. The user opens the employer page, fills and submits manually, then explicitly confirms submission in the dashboard. Opening a URL never sets `APPLIED`; no application form or CAPTCHA is automated. Application status changes and job review transitions appear in the audit timeline. See [docs/api-specification.md](docs/api-specification.md) and [docs/database-design.md](docs/database-design.md).

## Dashboard and application tracking

The Phase 7 workspace shows authenticated database counts and recent activity, lets you search and paginate the application pipeline, inspect job/resume/match/document/checklist details, and edit private application notes. Application status changes follow server-side transition rules; `READY_TO_APPLY` and `APPLIED` still require the Phase 6 approval and explicit submission-confirmation paths. Interviews and follow-ups support timezone-aware scheduling (Asia/Kolkata by default), edits, completion, and cancellation. Analytics show actual collection, match, application, and source records. Conversion percentages are suppressed until at least five submitted applications are in the sample. No notifications or scheduled worker were added.

## Architecture and plan

See [docs/architecture.md](docs/architecture.md), [docs/requirements.md](docs/requirements.md), [docs/database-design.md](docs/database-design.md), [docs/api-specification.md](docs/api-specification.md), and [docs/implementation-plan.md](docs/implementation-plan.md).

## Security baseline

Do not commit `.env`, credentials, resume files, or personal data. External listing and email content will be treated as untrusted input. Connectors must use permitted APIs, feeds, public pages, or user-authorized integrations and must not bypass access controls or anti-bot measures. Application submission remains a user action.
