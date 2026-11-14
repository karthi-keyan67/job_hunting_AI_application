# Database design — Phases 2–7

PostgreSQL is the application database. SQLAlchemy 2.x models use UUID primary keys, timezone-aware timestamps, PostgreSQL `JSONB` for flexible metadata, foreign keys, unique constraints, named indexes, and native enums. Alembic is the schema authority; application startup never calls `create_all`. Tests run against PostgreSQL as well.

The requested 17 domain tables are implemented. `auth_refresh_tokens` is an additional security table required to support hashed refresh-token storage, rotation, replay detection, and revocation. No refresh token is stored in plaintext.

Phase 9 adds `auth_login_attempts`, keyed by a unique SHA-256 fingerprint with a fixed-window start and positive attempt count. Fingerprints use a server secret, client address, and normalized email; raw email/IP values are not persisted. The table has a window index for stale-record cleanup. Revision `f18a3d7c9b20` is additive and follows the Phase 8 head.

Phase 10 adds `google_oauth_states` (hashed one-use state, owner, expiry, consumption timestamp) and `google_oauth_connections` (one per user, encrypted provider credential JSON, granted scopes, expiry, revocation timestamp, optional Gmail address). Credential ciphertext uses the configured Fernet key; raw access and refresh tokens are not stored in database columns. These tables are introduced by additive revision `a9210df6c5be`.

```mermaid
erDiagram
  USERS ||--o| USER_PROFILES : has
  USERS ||--o| JOB_PREFERENCES : configures
  USERS ||--o{ RESUMES : owns
  RESUMES ||--|{ RESUME_VERSIONS : versions
  USERS ||--o{ AUTH_REFRESH_TOKENS : authenticates
  USERS ||--o{ NOTIFICATIONS : receives
  USERS ||--o{ JOB_MATCHES : evaluated_for
  USERS ||--o{ MATCHING_REQUEST_LIMITS : rate_limited
  USERS ||--o{ JOB_REVIEWS : reviews
  JOB_REVIEWS ||--o{ JOB_REVIEW_EVENTS : history
  USERS ||--o{ APPLICATIONS : tracks
  JOB_SOURCES ||--o{ JOBS : publishes
  JOB_SOURCES ||--o{ COLLECTION_RUNS : records
  JOBS ||--o{ JOB_SKILLS : lists
  JOBS ||--o{ JOB_DUPLICATES : candidate
  JOBS ||--o{ JOB_DUPLICATES : duplicate
  JOBS ||--o{ JOB_MATCHES : matched_as
  RESUME_VERSIONS ||--o{ JOB_MATCHES : matched_with
  JOBS ||--o{ JOB_REVIEWS : reviewed_as
  JOBS ||--o{ APPLICATIONS : applied_for
  APPLICATIONS ||--o{ APPLICATION_EVENTS : records
  APPLICATIONS ||--o{ APPLICATION_DRAFTS : contains
  APPLICATIONS ||--o{ APPLICATION_APPROVALS : gates
  APPLICATIONS ||--o| APPLICATION_CHECKLISTS : checks
  APPLICATIONS ||--o{ APPLICATION_AUDIT_LOGS : audits
  APPLICATIONS ||--o{ INTERVIEWS : schedules
  APPLICATIONS ||--o{ FOLLOW_UPS : tracks
  JOB_REVIEWS ||--o{ APPLICATION_AUDIT_LOGS : job_review_audit
  RESUME_VERSIONS ||--o{ APPLICATIONS : selected_for
  JOB_MATCHES ||--o{ APPLICATIONS : based_on

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
  JOB_MATCHES { uuid id PK, uuid user_id FK, uuid job_id FK, uuid resume_version_id FK, numeric overall_score, numeric confidence, jsonb ai_analysis }
  MATCHING_REQUEST_LIMITS { uuid id PK, uuid user_id FK, timestamptz window_started_at, integer request_count }
  JOB_REVIEWS { uuid id PK, uuid user_id FK, uuid job_id FK, enum status }
  JOB_REVIEW_EVENTS { uuid id PK, uuid job_review_id FK, uuid user_id FK, string status, text rejection_reason }
  APPLICATIONS { uuid id PK, uuid user_id FK, uuid job_id FK, uuid resume_version_id FK, uuid job_match_id FK, uuid job_review_id FK, enum status }
  INTERVIEWS { uuid id PK, uuid user_id FK, uuid application_id FK, timestamptz scheduled_at, string timezone, enum status }
  FOLLOW_UPS { uuid id PK, uuid user_id FK, uuid application_id FK, timestamptz due_at, string timezone, enum status, timestamptz completed_at }
  APPLICATION_EVENTS { uuid id PK, uuid application_id FK, string event_type }
  COLLECTION_RUNS { uuid id PK, uuid source_id FK, enum status, timestamptz started_at }
  NOTIFICATIONS { uuid id PK, uuid user_id FK, jsonb payload }
  APPLICATION_DRAFTS { uuid id PK, uuid application_id FK, enum draft_type, integer version, text body, enum status, jsonb evidence }
  APPLICATION_APPROVALS { uuid id PK, uuid application_id FK, enum approval_type, jsonb draft_version_ids, jsonb checklist_snapshot }
  APPLICATION_CHECKLISTS { uuid id PK, uuid application_id FK, jsonb checks }
  APPLICATION_AUDIT_LOGS { uuid id PK, uuid application_id FK nullable, uuid job_review_id FK nullable, uuid actor_user_id FK, string action, jsonb details }
```

Email is normalized to lowercase before account lookup and insertion and protected by a unique index. A unique `(user_id, job_id)` constraint on applications prevents duplicate applications. A source plus external ID uniquely identifies a collected job. User-owned profile, preference, resume, token, match, review, notification, and application rows use foreign keys with deliberate cascade/restrict behavior.

The Phase 2 revision is `backend/alembic/versions/c36174d281c7_create_phase_2_core_schema.py`. Phase 3 adds `backend/alembic/versions/83b5a91c2e47_resume_versions_and_parsing.py`, which preserves existing resume rows as version 1 and refuses downgrade while any resume/version records remain. Resume binaries are stored outside the database with opaque generated storage keys; database metadata holds SHA-256 digests, source filenames, extracted text, parsed contact/skill data, and parsing status. The default-resume partial unique index guarantees at most one default per user.

Private uploads are held in the Docker `resume_data` volume (or `RESUME_STORAGE_ROOT` for local operation), with random storage keys and restricted file permissions. PDF/DOCX files are size-limited and validated before storage. Parsing is local and deterministic; OCR is not included.

Phase 4 revisions `a7d91b2f4c30` and `b68e21c4a90f` are additive. They add source ownership, normalized job fields, typed skills, JSONB collection metadata and completion/error fields, run counters, and `job_duplicates` provenance records. Source plus external ID remains unique. A partial unique index permits at most one `RUNNING` collection per source. Candidate duplicates retain both source records and link them for review; ingestion does not merge them. Compatibility columns from earlier phases are retained and populated while older data and code paths remain supported.

Phase 5 revision `c5198a0fd732` adds `excluded_roles` and `employment_types` to preferences; criterion scores, confidence, eligibility, resume-version FK, JSONB analysis/skill/evidence fields, and input fingerprint columns to `job_matches`; and `matching_request_limits` for atomic per-user PostgreSQL rate limiting. The old one-row-per-user/job constraint is replaced by unique `(user_id, job_id, input_fingerprint)`. Identical inputs reuse their row; changed inputs create a new history row. Legacy `score` and `details` fields remain for compatibility. The schema indexes user, job, overall score, eligibility, and rate-limit window. Resume versions referenced by matches cannot be deleted.

Phase 6 revision `d63fa8bc1201` extends existing workflow tables. A unique `(user_id, job_id)` review row stores current status and `job_review_events` preserves transitions. Applications link the selected resume version, match result, and review; unique `(user_id, job_id)` prevents duplicate applications. Drafts are versioned by `(application_id, draft_type, version)` with generated/edited/approved/superseded states, evidence, provider model, and prompt version. Approval records snapshot exact draft IDs and checklist JSON. Audit entries cover job review actions before an application exists and application events afterward. A PostgreSQL trigger rejects audit row updates/deletes; test database cleanup explicitly enables a transaction-local cleanup setting. Downgrade refuses to discard job-review audit rows that cannot be represented by the earlier schema.

Phase 7 revision `e4a62f8b13c7` is additive. It adds nullable private `applications.notes`, `interviews`, and `follow_ups`. Both scheduling entities reference their user and application, use UUID keys and timezone-aware timestamps, retain an IANA timezone label, and have user/due-time and application/due-time indexes. Interview and follow-up status use PostgreSQL enums. Delete API actions cancel records rather than physically removing history; changes append audit events. No notification or recurrence tables were added.

## Phase 8 automation and notifications

Phase 8 adds only additive revisions `f38b2c1a90de`, `c91e4d6a2f70`, `d0e4f26b8a31`, and `e26b7a10c94d` on top of Phase 7. `automation_settings` is unique per user and stores enablement, user timezone, email/in-app category preferences, match threshold, quiet hours, and reminder lead intervals (`JSONB`). Existing accounts receive a default settings row through a data-preserving additive backfill; newly registered accounts receive defaults at registration. `automation_executions` persists unique scheduled/manual run keys, scheduled/start/completion times, status, duration, retries, and sanitized aggregate error details. `worker_heartbeats` stores scheduler status, heartbeat, last success, and next run.

The existing `notifications` table is extended as a transactional outbox: unique nullable `dedupe_key`, delivery status/attempt count, next retry time, last delivery time, and sanitized error type. Email delivery only processes pending rows for opted-in users; an absent SMTP configuration results in no email send. User ownership is enforced by the notification foreign key and every inbox query.

`collection_runs` gains collection duration and retry count plus matching duration and matching-failure metrics. Existing source/job/run constraints and tables remain intact. All Phase 8 schema changes are represented by Alembic; `create_all` is not used for deployment migrations.
