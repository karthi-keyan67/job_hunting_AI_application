# Database design — Phases 2–4

PostgreSQL is the application database. SQLAlchemy 2.x models use UUID primary keys, timezone-aware timestamps, PostgreSQL `JSONB` for flexible metadata, foreign keys, unique constraints, named indexes, and native enums. Alembic is the schema authority; application startup never calls `create_all`. Tests run against PostgreSQL as well.

The requested 17 domain tables are implemented. `auth_refresh_tokens` is an additional security table required to support hashed refresh-token storage, rotation, replay detection, and revocation. No refresh token is stored in plaintext.

```mermaid
erDiagram
  USERS ||--o| USER_PROFILES : has
  USERS ||--o| JOB_PREFERENCES : configures
  USERS ||--o{ RESUMES : owns
  RESUMES ||--|{ RESUME_VERSIONS : versions
  USERS ||--o{ AUTH_REFRESH_TOKENS : authenticates
  USERS ||--o{ NOTIFICATIONS : receives
  USERS ||--o{ JOB_MATCHES : evaluated_for
  USERS ||--o{ JOB_REVIEWS : reviews
  USERS ||--o{ APPLICATIONS : tracks
  JOB_SOURCES ||--o{ JOBS : publishes
  JOB_SOURCES ||--o{ COLLECTION_RUNS : records
  JOBS ||--o{ JOB_SKILLS : lists
  JOBS ||--o{ JOB_DUPLICATES : candidate
  JOBS ||--o{ JOB_DUPLICATES : duplicate
  JOBS ||--o{ JOB_MATCHES : matched_as
  JOBS ||--o{ JOB_REVIEWS : reviewed_as
  JOBS ||--o{ APPLICATIONS : applied_for
  APPLICATIONS ||--o{ APPLICATION_EVENTS : records
  APPLICATIONS ||--o{ APPLICATION_DRAFTS : contains
  APPLICATIONS ||--o{ APPLICATION_APPROVALS : gates
  APPLICATIONS ||--o| APPLICATION_CHECKLISTS : checks
  APPLICATIONS ||--o{ APPLICATION_AUDIT_LOGS : audits

  USERS { uuid id PK, string email UK, string password_hash }
  USER_PROFILES { uuid id PK, uuid user_id FK, string full_name }
  JOB_PREFERENCES { uuid id PK, uuid user_id FK, jsonb roles, jsonb skills }
  RESUMES { uuid id PK, uuid user_id FK, string title, boolean is_default }
  RESUME_VERSIONS { uuid id PK, uuid resume_id FK, integer version_number, string storage_key, enum parsing_status, jsonb parsed_data }
  AUTH_REFRESH_TOKENS { uuid id PK, uuid user_id FK, string token_hash, uuid family_id }
  JOB_SOURCES { uuid id PK, uuid user_id FK, string name, enum status, jsonb configuration }
  JOBS { uuid id PK, uuid source_id FK, string external_id, string title, string company, jsonb raw_data }
  JOB_SKILLS { uuid id PK, uuid job_id FK, string skill_name, enum skill_type }
  JOB_DUPLICATES { uuid id PK, uuid job_id FK, uuid duplicate_job_id FK, string reason }
  JOB_MATCHES { uuid id PK, uuid user_id FK, uuid job_id FK, numeric score }
  JOB_REVIEWS { uuid id PK, uuid user_id FK, uuid job_id FK, enum status }
  APPLICATIONS { uuid id PK, uuid user_id FK, uuid job_id FK, enum status }
  APPLICATION_EVENTS { uuid id PK, uuid application_id FK, string event_type }
  COLLECTION_RUNS { uuid id PK, uuid source_id FK, enum status, timestamptz started_at }
  NOTIFICATIONS { uuid id PK, uuid user_id FK, jsonb payload }
  APPLICATION_DRAFTS { uuid id PK, uuid application_id FK, jsonb content }
  APPLICATION_APPROVALS { uuid id PK, uuid application_id FK, enum approval_type }
  APPLICATION_CHECKLISTS { uuid id PK, uuid application_id FK, jsonb checks }
  APPLICATION_AUDIT_LOGS { uuid id PK, uuid application_id FK, jsonb details }
```

Email is normalized to lowercase before account lookup and insertion and protected by a unique index. A unique `(user_id, job_id)` constraint on applications prevents duplicate applications. A source plus external ID uniquely identifies a collected job. User-owned profile, preference, resume, token, match, review, notification, and application rows use foreign keys with deliberate cascade/restrict behavior.

The Phase 2 revision is `backend/alembic/versions/c36174d281c7_create_phase_2_core_schema.py`. Phase 3 adds `backend/alembic/versions/83b5a91c2e47_resume_versions_and_parsing.py`, which preserves existing resume rows as version 1 and refuses downgrade while any resume/version records remain. Resume binaries are stored outside the database with opaque generated storage keys; database metadata holds SHA-256 digests, source filenames, extracted text, parsed contact/skill data, and parsing status. The default-resume partial unique index guarantees at most one default per user.

Private uploads are held in the Docker `resume_data` volume (or `RESUME_STORAGE_ROOT` for local operation), with random storage keys and restricted file permissions. PDF/DOCX files are size-limited and validated before storage. Parsing is local and deterministic; OCR is not included.

Phase 4 revisions `a7d91b2f4c30` and `b68e21c4a90f` are additive. They add source ownership, normalized job fields, typed skills, JSONB collection metadata and completion/error fields, run counters, and `job_duplicates` provenance records. Source plus external ID remains unique. A partial unique index permits at most one `RUNNING` collection per source. Candidate duplicates retain both source records and link them for review; ingestion does not merge them. Compatibility columns from earlier phases are retained and populated while older data and code paths remain supported.
