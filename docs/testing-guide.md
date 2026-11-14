# Testing and verification guide

## Backend PostgreSQL suite

Use a dedicated test database, never the application DB. `TEST_DATABASE_URL` may point at a dedicated DB, or the Compose verification profile uses `VERIFY_DATABASE_NAME`. Tests run Alembic to head and clean test-owned rows but retain the database/schema.

```powershell
docker compose -p job-hunting-agent-p2verify --env-file .env --profile verification run --rm backend-test
```

The Python suite covers registration/authentication, refresh rotation/revocation, profile/preferences, resume and job workflows, matching/application preparation, dashboard and automation APIs, ownership, PostgreSQL constraints, notification outbox behavior, quiet hours, retries, and scheduler advisory-lock/timeout/recovery paths.

## Frontend and static checks

```powershell
cd frontend
npm ci
npm audit
npm audit --omit=dev
npm run lint
npm test
npm run build
```

ESLint currently exits successfully with 38 explicit-`any` warnings. For backend static checks and dependency audit, use the verification image:

```powershell
docker compose -p job-hunting-agent-p2verify --env-file .env --profile verification run --rm backend-test ruff check app tests
docker compose -p job-hunting-agent-p2verify --env-file .env --profile verification run --rm backend-test pip-audit -r requirements.txt
```

Current checks pass Ruff and report no known Python or npm vulnerabilities for checked dependency sets.

## Production image and HTTPS checks

```powershell
docker compose -f docker-compose.production.yml --env-file deploy/.env.production config --quiet
docker compose -f docker-compose.production.yml --env-file deploy/.env.production build backend worker frontend proxy
```

Production Caddy syntax can be checked with `caddy validate`. To test HTTPS without a public deployment, use an isolated localhost proxy with `APP_DOMAIN=localhost` and Caddy's internal test CA. Verify TLS response headers, frontend `/healthz`, and API forwarding before changing host exposure. Never request a public certificate during local verification.

## Backup and restore test

Take a custom-format `pg_dump -Fc` backup of the project database only. Restore it into a newly created, uniquely named database using `pg_restore --exit-on-error`. Compare table counts, key representative records (without printing personal contents), and Alembic version. Keep the disposable restored DB unless deletion is separately approved. Do not restore over, drop, or downgrade the source database. Test encryption and off-host key separation in the operational backup platform.

## Live integrations and end-to-end data

Only make external provider calls when valid credentials and an explicitly controlled test account/recipient are configured. The current checkout has no OpenAI, Google OAuth, or SMTP credentials; do not claim live tests for them. Server-side Gmail OAuth is implemented, but leave it disabled until credentials are configured and a controlled live account test passes. Use only authorized public career pages or official APIs/feeds. No live collection was forced against user sources, and no job application was submitted.

## Authenticated API smoke workflow

Against a dedicated test account/database, register/login, call `/api/v1/auth/me`, update `/api/v1/profile` and `/api/v1/preferences`, and verify bearer access plus refresh/revocation. Existing test routes exercise these against PostgreSQL. See the README for PowerShell request examples.
