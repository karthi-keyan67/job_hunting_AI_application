# Database design

The target schema follows the requested PostgreSQL design. Phase 1 creates no tables; SQLAlchemy models and Alembic migrations begin in Phase 2, when ownership and lifecycle constraints can be represented together.

```mermaid
erDiagram
  USERS ||--|| USER_PROFILES : has
  USERS ||--o{ RESUMES : owns
  USERS ||--|| JOB_PREFERENCES : configures
  USERS ||--o{ JOB_REVIEWS : reviews
  USERS ||--o{ APPLICATIONS : tracks
  USERS ||--o{ NOTIFICATIONS : receives
  USERS ||--o{ COLLECTION_RUNS : triggers
  JOB_SOURCES ||--o{ JOBS : provides
  JOB_SOURCES ||--o{ COLLECTION_RUNS : records
  JOBS ||--o{ JOB_SKILLS : requires
  JOBS ||--o{ JOB_MATCHES : evaluated_as
  USERS ||--o{ JOB_MATCHES : receives
  JOBS ||--o{ JOB_REVIEWS : reviewed_as
  JOBS ||--o{ APPLICATIONS : applied_for
  APPLICATIONS ||--o{ APPLICATION_EVENTS : records
  APPLICATIONS ||--o{ APPLICATION_DRAFTS : contains
  APPLICATIONS ||--o{ APPLICATION_APPROVALS : requires
  APPLICATIONS ||--o| APPLICATION_CHECKLISTS : gates
  APPLICATIONS ||--o{ APPLICATION_AUDIT_LOGS : audits

  USERS { uuid id PK }
  USER_PROFILES { uuid user_id PK, jsonb profile_data }
  RESUMES { uuid id PK, uuid user_id FK, text storage_key }
  JOB_PREFERENCES { uuid user_id PK, jsonb preferences }
  JOB_SOURCES { uuid id PK, text connector_type, text status }
  JOBS { uuid id PK, uuid source_id FK, text external_id, text original_description }
  JOB_SKILLS { uuid id PK, uuid job_id FK, text skill }
  JOB_MATCHES { uuid id PK, uuid user_id FK, uuid job_id FK, numeric score }
  APPLICATIONS { uuid id PK, uuid user_id FK, uuid job_id FK, text status }
  APPLICATION_EVENTS { uuid id PK, uuid application_id FK, text event_type }
  COLLECTION_RUNS { uuid id PK, uuid source_id FK, timestamptz started_at }
  NOTIFICATIONS { uuid id PK, uuid user_id FK, jsonb payload }
  JOB_REVIEWS { uuid id PK, uuid user_id FK, uuid job_id FK, text status }
  APPLICATION_DRAFTS { uuid id PK, uuid application_id FK, jsonb content }
  APPLICATION_APPROVALS { uuid id PK, uuid application_id FK, text approval_type }
  APPLICATION_CHECKLISTS { uuid application_id PK, jsonb checklist }
  APPLICATION_AUDIT_LOGS { uuid id PK, uuid application_id FK, text action }
```

All IDs will be UUIDs, timestamps UTC, foreign keys enforced, and flexible integration details stored in JSONB. Indexes will cover ownership and status queries; unique constraints will prevent duplicate source jobs and duplicate user/job applications. Detailed columns and delete behavior will be recorded in migrations rather than duplicated across hand-maintained diagrams.
