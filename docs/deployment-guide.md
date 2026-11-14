# Deployment and operations guide

## Current deployment boundary

The provided Compose setup is a local development and verification stack. It exposes PostgreSQL on host port 5433, FastAPI on 8000, and the Vite development server on 5173. The frontend is not a production static build and the stack does not configure TLS, a reverse proxy, backups, secret management, or a production network policy. Do not publish these ports directly to the internet.

The project PostgreSQL service is PostgreSQL 16 in Compose and uses the named `postgres_data` volume. In the verified local setup its host binding is 5433 because another PostgreSQL instance occupies 5432. Compose clients use service port 5432. Preserve this port arrangement and volume when operating the existing stack.

## Configuration

Copy `.env.example` to `.env` and provide unique values for `POSTGRES_PASSWORD` and `JWT_SECRET`. Set `APP_ENV=production` only with HTTPS CORS origins and production credentials. Keep secrets out of source control and logs. Other settings and defaults are described in `.env.example` and the README.

## Safe startup and migration

For the existing local project:

```powershell
docker compose -p job-hunting-agent-p2verify --env-file .env ps
docker compose -p job-hunting-agent-p2verify --env-file .env exec backend python -m alembic current
docker compose -p job-hunting-agent-p2verify --env-file .env exec backend python -m alembic upgrade head
docker compose -p job-hunting-agent-p2verify --env-file .env ps
```

Review the proposed migration and take a verified database backup before applying schema changes to important data. Migrations are additive; do not use `docker compose down -v`, `dropdb`, or `alembic downgrade` on the application database. Downgrade testing belongs only on a newly created disposable verification database.

## Backup and recovery

Schedule encrypted PostgreSQL backups using `pg_dump`/`pg_basebackup` appropriate to your recovery goals, store them outside the Docker host, restrict access, and regularly test restore to a separate database. The `resume_data` volume contains private source documents and must be backed up and restored separately with restrictive permissions. Document key rotation and recovery access. Never test restores over the live project database or volume.

Before any public deployment, use a production ASGI server/container configuration, TLS reverse proxy, private PostgreSQL network, non-root backend/worker image with compatible resume volume ownership, secure secret manager, CSP/security headers, backup monitoring, and an operational incident/recovery plan. These are not configured by this development Compose stack.
