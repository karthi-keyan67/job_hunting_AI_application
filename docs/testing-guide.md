# Testing and verification guide

## Backend PostgreSQL tests

Use a dedicated PostgreSQL test database, never the application database. Configure `TEST_DATABASE_URL` (asyncpg URL), or use `VERIFY_DATABASE_NAME` with the project PostgreSQL credentials. The pytest fixture applies Alembic to head and cleans test-owned rows; the database/schema itself is retained.

```powershell
cd backend
python -m pip install -r requirements-dev.txt
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://USER:PASSWORD@HOST:5433/DEDICATED_TEST_DB'
python -m pytest -q --cov=app --cov-report=term-missing
```

In the existing Docker Compose project:

```powershell
docker compose -p job-hunting-agent-p2verify --env-file .env --profile verification run --rm backend-test
```

The verification profile uses the configured verification database and does not reset or drop it. Do not point it at a database with user data.

## Frontend checks

```powershell
cd frontend
npm ci
npm test
npm run lint
npm run build
npm audit --omit=dev
```

The current lint policy treats errors as failures and reports remaining explicit `any` usages as warnings.

## Migration checks

```powershell
cd backend
python -m alembic current
python -m alembic check
python -m alembic upgrade head
```

To verify the complete migration history, create a uniquely named, empty PostgreSQL database, run `upgrade head`, `downgrade base`, then `upgrade head` against that database only. Keep the verification database unless its removal is separately authorized. Never downgrade, reset, or drop the application database or volume.

## API smoke checks

Register and use the returned access token with `/api/v1/auth/me`, then read/update `/api/v1/profile` and `/api/v1/preferences`. Login and refresh examples are in the README. The test suite also exercises duplicate registration, refresh rotation/replay revocation, user ownership, profile and preference updates, database constraints, and the PostgreSQL health route.
