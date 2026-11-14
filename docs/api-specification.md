# API specification

Base URL: `/api/v1`. JSON error responses use FastAPI's `{"detail": ...}` structure. Authentication is a signed JWT bearer access token. Refresh tokens are accepted only by refresh/logout routes, persisted as SHA-256 digests, rotated at refresh, and revoked by logout or replay detection.

## Health

- `GET /health` — executes `SELECT 1`; returns `{"status":"ok","database":"ok"}` or HTTP 503 when the database is unavailable.

## Authentication

- `POST /auth/register` — JSON `{ "email", "password" }`; password must be 12–128 characters. Returns 201 and `{access_token, refresh_token, token_type, expires_in}`. Creates an empty profile and preferences record; does not infer personal data.
- `POST /auth/login` — same credentials; returns a token pair or generic 401.
- `POST /auth/refresh` — JSON `{ "refresh_token" }`; rotates token, invalidates the previous token, returns a new pair.
- `POST /auth/logout` — authenticated bearer access token plus JSON `{ "refresh_token" }`; revokes that token family and returns 204.
- `GET /auth/me` — authenticated; returns `{id, email, is_active}`.

Duplicate registration returns 409. Invalid, expired, replayed, or revoked tokens return 401. Email and body validation errors return 422.

## Profile and preferences

All routes require `Authorization: Bearer <access_token>` and only access the authenticated user's records.

- `GET /profile` / `PUT /profile` — full name, current designation/company, experience months, notice period days, salary range, currency, and bio. PUT is a full replacement of these fields and rejects invalid ranges.
- `GET /preferences` / `PUT /preferences` — target roles, required/optional skills, minimum/maximum experience, salary range, locations, work modes, excluded companies, and active status. PUT replaces the complete preference object.

New accounts receive empty profile and preference records with INR as the profile currency default. User-specific role/skill defaults are not inserted into application logic.

## Resumes

All endpoints require a bearer access token and are scoped to its owner. Uploads use multipart form data, accept PDF/DOCX only, and obey `MAX_RESUME_UPLOAD_BYTES` (5 MiB by default).

- `POST /resumes` — multipart `file` and optional `title`; creates resume and version 1.
- `GET /resumes` — list the user's resumes and all version metadata.
- `GET /resumes/{resume_id}` — one owned resume with version metadata and extracted text.
- `POST /resumes/{resume_id}/versions` — multipart `file`; appends next version. An identical SHA-256 file returns 409 unless `force_new_version=true` is supplied.
- `GET /resumes/{resume_id}/versions/{version_id}/download` — authenticated original file download.
- `POST /resumes/{resume_id}/default` — sets the user's default resume.
- `DELETE /resumes/{resume_id}` — removes the resume and its versions.
- `DELETE /resumes/{resume_id}/versions/{version_id}` — removes a non-final version; referenced application data is protected.

Malformed documents return 422, unsupported extensions return 415, oversized files return 413, and cross-user identifiers return 404. Parsing states are `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`, and `NEEDS_OCR`. Text extraction for PDF/DOCX is local; OCR and AI interpretation are out of scope.

## Job sources and jobs

All endpoints below require a bearer access token. Sources, runs, and jobs are scoped to the authenticated user. Connector configuration must not include credentials or tokens; secret-like fields are rejected/redacted.

- `GET /sources` — list owned sources.
- `POST /sources` — create a source (name, type, configuration, active state). Public career sources require a public HTTP(S) URL and configured selectors.
- `GET /sources/{source_id}` / `PATCH /sources/{source_id}` / `DELETE /sources/{source_id}` — inspect, update, or remove an owned source.
- `POST /sources/{source_id}/test` — validate connector configuration/access and report capability/status.
- `POST /sources/{source_id}/collect` — run one bounded collection pass. Database locking prevents overlapping runs. Unconfigured integrations return 409; unknown/foreign sources return 404.
- `GET /sources/{source_id}/runs` — list runs for an owned source.
- `GET /collection-runs` — list the user's collection history.
- `GET /jobs` — list owned jobs, with optional `search`, `location`, `work_mode`, `source_id`, `offset`, and `limit` filters.
- `POST /jobs/import` — manually import listing fields and a URL; the URL is validated and stored but never fetched by this endpoint. Exact source-scoped re-imports are idempotent.
- `GET /jobs/{job_id}` — get an owned job and provenance.
- `POST /jobs/{job_id}/refresh` — request collection for its source when a connector exists; manual and unsupported sources return 409.

Normalized job data includes title, company, location, work mode, description, apply URL, compensation and experience only when the source makes those values clear, skills, and provenance. Unknown salary/experience stays null. Cross-source duplicate candidates retain both records and are stored for review; records are not silently merged. Career page requests obey robots.txt, reject private/reserved destinations, do not follow redirects, and use bounded retries/rate limits. Gmail requires configured OAuth and an explicit sender allowlist. Portal scraping that requires login, bypasses anti-bot controls, or lacks an authorized API/feed is not implemented.

## Migration commands

Run from `backend` after PostgreSQL is available and `.env` contains `POSTGRES_*` (or `DATABASE_URL`) settings:

```powershell
python -m alembic upgrade head
python -m alembic current
python -m alembic downgrade base  # destructive schema rollback; local/dev only
```

The initial revision includes all Phase 2 models, including the auth refresh-token table. API startup does not create or alter tables. Phase 4 adds job source ownership and normalized fields, collection metadata, and provenance-preserving duplicate candidates through additive revisions `a7d91b2f4c30` and `b68e21c4a90f`.
