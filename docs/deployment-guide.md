# Deployment and operations guide

## Readiness boundary

`docker-compose.yml` remains the local development stack: Vite dev server, API on 8000, frontend on 5173, and project PostgreSQL on host port 5433. Keep PostgreSQL 17 on port 5432 separate. The current development backend/worker runtime is root and is not suitable for public exposure.

`docker-compose.production.yml` is a separate production-oriented profile. It builds non-root API/worker images, a static frontend runtime, and a non-root Caddy TLS proxy. PostgreSQL is on an internal-only network with no host port. Proxy ports bind to loopback by default. The profile was config-validated, images built, frontend security headers checked, and Caddy tested with a localhost TLS certificate. It has not been deployed, tested against a public DNS name, or exposed publicly.

## Production configuration and secrets

Copy `deploy/.env.production.example` to a private env file and replace the example domain and email. Create protected secret files referenced by `POSTGRES_PASSWORD_FILE`, `JWT_SECRET_FILE`, `OPENAI_API_KEY_FILE`, and `SMTP_PASSWORD_FILE`. The tracked `.example` files are empty placeholders and must never be used as real credentials. The secret directory is Git-ignored. Use a host secret manager or restrictive ACLs; generate a unique database password of at least 20 characters and JWT secret of at least 32 characters.

AI remains disabled when no key is present; keep `MATCHING_AI_ENABLED=false` until a valid key is injected through the secret file and a controlled live test is approved. SMTP remains off with no `SMTP_HOST`/`SMTP_FROM_EMAIL`; only enable it with a controlled test recipient. The server-side Gmail OAuth flow is implemented, but leave Gmail alert sources disabled until Google client credentials are configured and live authorization is verified. Configure `CORS_ORIGINS` as the exact HTTPS app origin (production Compose derives it from `APP_DOMAIN`).

## Startup and migration

Review Compose changes, configure secrets, and take a verified backup before applying migrations. The profile defaults to loopback binds and is not a public deployment command until domain/network/firewall settings are reviewed.

```powershell
docker compose -f docker-compose.production.yml --env-file deploy/.env.production config --quiet
docker compose -f docker-compose.production.yml --env-file deploy/.env.production up -d postgres
docker compose -f docker-compose.production.yml --env-file deploy/.env.production run --rm backend python -m alembic upgrade head
docker compose -f docker-compose.production.yml --env-file deploy/.env.production up -d backend worker frontend proxy
docker compose -f docker-compose.production.yml --env-file deploy/.env.production ps
```

Use immutable image tags for release/rollback. Migrations are additive; do not downgrade the production database as an application rollback. Revert the application image while leaving the forward-compatible schema in place. If data recovery is required, restore a backup into a new database, validate it, then switch connection configuration under an approved maintenance plan. Never overwrite the original database during restore testing.

For actual internet TLS, point a controlled domain to the host and, after explicit deployment approval, bind TCP 80/443 from a secured host firewall to Caddy. The current loopback mapping intentionally prevents public exposure. Caddy requires domain control and reachable challenge ports for public ACME issuance. HSTS is sent only by the TLS site.

## Authorized integrations

- **Career pages:** use only public pages for which collection is permitted. Respect robots policy, provider terms, request limits, and source-specific failure status. Verify each source with its owner account and a bounded test before enabling scheduled collection.
- **Job portals:** LinkedIn, Naukri, Indeed, and other listed portals stay unsupported unless an authorized API/feed integration is implemented. Do not use login scraping, CAPTCHA bypass, or anti-bot evasion.
- **Gmail:** read-only OAuth with encrypted server-side credentials is implemented. Configure OAuth client ID/secret, HTTPS redirect URI, and encryption key, then verify with a controlled account before enabling alerts.
- **OpenAI:** server-side key only; matching stays deterministic when the key/AI setting is absent. Test redaction, structured evidence, timeouts, invalid output, and provider failures with a controlled key before enablement. Never put the key in Vite variables.
- **SMTP:** configure host, port, STARTTLS, sender, and optional credentials through the secret/environment mechanism. Test only with an explicitly approved controlled recipient. The outbox retries are bounded and errors retain exception types rather than credentials/provider response bodies.

## Scheduler operation

The worker schedules at 00:00, 06:00, 12:00, and 18:00 in `AUTOMATION_TIMEZONE` (default `Asia/Kolkata`). PostgreSQL advisory locking prevents multiple schedulers from running concurrently; durable execution keys prevent duplicates. `restart: unless-stopped`, health checks, `init`, and stop grace periods support process recovery. Do not force a run against real user sources for a health test. Use a controlled account and authorized source to verify collection, matching, outbox, quiet hours, and retry behavior end to end.

## Backup and recovery

The verification used PostgreSQL `pg_dump -Fc` on only the project database, restored with `pg_restore` to a newly created disposable database, compared representative table counts and Alembic head, and removed the temporary dump. The source database was empty for the sampled user/job/application tables. The disposable restore database is retained. This test did not validate long-term encryption, off-host retention, PITR, or resume storage recovery.

For operational backups, encrypt dumps with keys managed separately from the backup, transfer them to access-restricted off-host storage, retain according to policy, and test restore into a new disposable DB. Back up the resume volume independently with restrictive permissions and restore it into a new volume. Never use `docker compose down -v`, `dropdb`, or restore over a live database/volume.

## Resource and data notes

Production Compose defines service CPU/memory limits and persistent named volumes for database, resumes, and Caddy cert/config data. Production creates a separate fresh `resume_data` volume; migrating existing development resume files requires a separately reviewed copy and ownership plan. No volume was migrated or altered during this verification.
