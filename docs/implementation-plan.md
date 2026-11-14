# Implementation plan

| Phase | Scope | Status |
|---|---|---|
| 1 | Architecture docs, project foundation, Docker/PostgreSQL, FastAPI health, React shell, environment template | Complete |
| 2 | SQLAlchemy models, Alembic, authentication, profile, preferences | Complete; PostgreSQL verified |
| 3 | Secure resume upload, parsing, versions | Complete |
| 4 | Authorized connectors, ingestion, normalization, deduplication | Complete; PostgreSQL verified |
| 5 | Deterministic filters, AI matching, score explanations | Pending |
| 6 | Job review, content drafts, approval checklist, manual submission handoff and audit | Pending |
| 7 | Dashboard workflows and application tracking | Pending |
| 8 | Six-hour worker schedule, notifications, analytics, monitoring | Pending |
| 9 | Comprehensive tests, security review, deployment hardening | Pending |

## Phase 2 PostgreSQL verification — 2026-11-14

### Passed

- Docker Desktop daemon reachable (Docker Engine 29.9.2). Existing `postgres_db` (`postgres:17`) occupied host port 5432. It and its `psql_pgdata` volume were left untouched.
- Project PostgreSQL 16 started under Compose project `job-hunting-agent-p2verify` with host port **5433 → container 5432** and a new volume `job-hunting-agent-p2verify_postgres_data`.
- Project database `job_hunting` accepted connections and reached Alembic revision `c36174d281c7 (head)`. The application-resolved URL was `postgresql+asyncpg://job_hunting:***@postgres:5432/job_hunting`; the health endpoint returned `{"status":"ok","database":"ok"}`.
- Separate `job_hunting_verify` database completed an explicit Alembic downgrade to base and upgrade to head. `alembic check` reported no new operations; the verification database was left at head.
- PostgreSQL catalog inspection found all 18 domain/security tables, 39 UUID columns, 15 JSONB columns, five native enums, 20 foreign keys, and 46 non-primary indexes.
- PostgreSQL pytest run: **15 passed**. The suite exercised registration, password hashing, duplicate rejection, login, JWT auth, refresh/revocation, profile/preferences, database constraints, and migration setup/teardown.
- Live HTTP smoke checks against the running FastAPI/PostgreSQL service passed for registration (201), login (200), `/auth/me`, and profile/preferences GET and PUT. The synthetic smoke-test account was removed afterward.
- All Compose services report healthy: PostgreSQL on 5433, backend on 8000, frontend on 5173. Existing PostgreSQL 17 remains running on 5432.
- Production app and migration code use PostgreSQL/asyncpg only. Tests require PostgreSQL; no SQLite-specific test fallback remains.

### Resolved during verification

The first PostgreSQL pytest run exposed reuse of one async engine across pytest event loops (8 passed, 7 setup errors). The fixture now creates and disposes an engine per test; the complete PostgreSQL suite then passed 15/15.

## Phase 3 implementation and verification — 2026-11-14

### Passed

- Added the additive Alembic revision `83b5a91c2e47_resume_versions_and_parsing`; the existing Phase 2 revision was not changed. The project's `job_hunting` PostgreSQL database upgraded successfully and is at the Phase 3 head.
- `alembic check` against `job_hunting` reported no new operations. PostgreSQL catalog inspection confirmed UUID primary/foreign keys, JSONB `parsed_data`, native `resume_parsing_status` enum, resume/version checks and uniqueness, the version foreign key, and the one-default-per-user partial unique index.
- Performed an explicit Alembic downgrade to base and upgrade to head against only disposable `job_hunting_verify`. The verification database was re-upgraded after the test fixture's teardown; the application database was not downgraded or cleared.
- PostgreSQL backend tests: **18 passed**. Coverage includes auth/profile/preferences regression tests and resume authorization, PDF/DOCX parsing, invalid/empty uploads, duplicate detection, version preservation, default selection, ownership isolation, download byte equality, and deletion.
- Frontend Vitest: **3 passed**. `npm run build` completed successfully.
- Rebuilt FastAPI and React services. PostgreSQL, backend, and frontend are healthy in Compose; `/api/v1/health` reports database `ok`. OpenAPI includes registration/login and resume endpoints.
- Production application, migration, and test code contain no SQLite/aiosqlite assumptions and the app does not use `create_all`.
- The project PostgreSQL service stays on host port 5433 because the user's separate PostgreSQL 17 container owns port 5432. Its container and volume were untouched. Resume files use the added private `resume_data` volume.

### Limitations

- OCR for image-only/scanned resumes is not implemented; these are retained and labeled `NEEDS_OCR`.
- Parsed fields are heuristic local extraction and are not AI-enriched. The maximum upload is configurable and defaults to 5 MiB.
- Phase 4 verification and implementation are recorded below.

### Failed or blocked

None remain. No existing database, container, or volume was reset or deleted. Phase 3 is complete.

## Phase 4 implementation and PostgreSQL verification — 2026-11-14

### Passed

- Added additive Alembic revisions `a7d91b2f4c30` and `b68e21c4a90f`. The application database `job_hunting` is at `b68e21c4a90f (head)`; Alembic `check` reports **No new upgrade operations detected**. The disposable `job_hunting_verify` database completed downgrade/upgrade migration testing and was left upgraded at head. No application data was reset or dropped.
- Docker Compose project `job-hunting-agent-p2verify` rebuilt successfully. PostgreSQL (host port 5433), FastAPI (8000), and frontend (5173) all report healthy; `/api/v1/health` returned `{"status":"ok","database":"ok"}`. The user's separate PostgreSQL 17 service on 5432 was left untouched.
- PostgreSQL catalog inspection found **21 tables, 45 UUID columns, 19 JSONB columns, six native enums, 24 foreign keys, and 58 indexes** (including primary-key indexes). The Phase 4 source ownership, normalized job fields, duplicate provenance and collection locking schema are present.
- PostgreSQL backend suite: **32 passed**. Coverage includes registration/login/token rotation/revocation, profile/preferences, resume regression, connector parsers and safety, manual import, source ownership, unsupported status, duplicate provenance, idempotent upsert, collection failure, and the per-source running lock.
- Frontend Vitest: **6 passed**. `npm run build` completed successfully.
- OpenAPI exports `/api/v1/sources`, `/api/v1/jobs`, manual import, refresh, source testing/collection/history, and collection-run history endpoints. Health check and running application use PostgreSQL.
- Production application and migration code contain no SQLite/aiosqlite assumptions and application startup does not call `create_all`.

### Limitations and required setup

- No user-authorized live career-page URL was configured, so external live collection was not attempted. Connector behavior was tested with controlled fixtures and HTTP mocks. Add a permitted public career page and its CSS selectors in the UI to exercise a real source.
- Gmail remains fail-closed until OAuth is configured and sender addresses are allowlisted. Portals without authorized APIs/feeds are reported unsupported. Manual import remains available and does not fetch the supplied URL.
- Collection is manually triggered/one-shot; recurring scheduling, AI matching, and application automation are outside Phase 4.

### Failed or blocked

None. No existing PostgreSQL container, volume, database, or user data was modified or deleted. Phase 5 has not started and requires separate approval.
