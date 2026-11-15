# API specification

Base URL: `/api/v1`. JSON error responses use FastAPI's `{"detail": ...}` structure. Authentication is a signed JWT bearer access token. Refresh tokens are accepted only by refresh/logout routes, persisted as SHA-256 digests, rotated at refresh, and revoked by logout or replay detection. Login failures are rate-limited by a privacy-preserving PostgreSQL fingerprint; exceeding `AUTH_LOGIN_MAX_ATTEMPTS` within `AUTH_LOGIN_WINDOW_MINUTES` returns HTTP 429 and a `Retry-After` header.

## Health

- `GET /health` — executes `SELECT 1`; returns `{"status":"ok","database":"ok"}` or HTTP 503 when the database is unavailable.

## Authentication

- `POST /auth/register` — JSON `{ "email", "password" }`; password must be 12–128 characters. Returns 201 and `{access_token, refresh_token, token_type, expires_in}`. Creates an empty profile and preferences record; does not infer personal data.
- `POST /auth/login` — same credentials; returns a token pair or generic 401.
- `POST /auth/refresh` — JSON `{ "refresh_token" }`; rotates token, invalidates the previous token, returns a new pair.
- `POST /auth/logout` — authenticated bearer access token plus JSON `{ "refresh_token" }`; revokes that token family and returns 204.
- `GET /auth/me` — authenticated; returns `{id, email, is_active}`.
- `GET /integrations/gmail/status`, `POST /integrations/gmail/authorize`, `GET /integrations/gmail/callback`, and `DELETE /integrations/gmail/connection` — connect/revoke the owner's Gmail OAuth connection. The callback is bound to a hashed, expiring one-use state; only `gmail.readonly` is requested. Tokens are encrypted at rest and never returned to the browser. These endpoints fail closed until Google client credentials, HTTPS callback URI, and an encryption key are configured.
- `GET /integrations/gmail/reviews?status=NEEDS_REVIEW&limit=100` — list the authenticated user's unknown or unparseable allowlisted alerts. `status` supports `NEEDS_REVIEW`, `REVIEWED`, `IGNORED`, `FILTERED`, or `ALL`.
- `PATCH /integrations/gmail/reviews/{review_id}` — JSON `{ "status": "REVIEWED" | "IGNORED" }`; ownership-scoped acknowledgement of a review item.

## Job portal connections

All endpoints require a bearer token and are scoped to the authenticated user. Gmail is a separate mailbox authorization; it does not connect or authenticate the user to any job portal. Direct portal integrations remain unavailable unless an approved job-seeker API or permitted feed is added.

- `GET /integrations/job-portals` — capability and status cards for LinkedIn, Naukri, Indeed, Instahyre, Cutshort, and Hirist, including Gmail connection state, per-platform alert-source settings, latest sync result, and direct-integration limitations. `portal_account_connected` remains false for email-alert integrations.
- `PUT /integrations/job-portals/{platform}/alerts` — create or replace the per-user Gmail alert source settings with `{ "allowed_senders": ["jobs@example.com"], "required_terms": [], "label_ids": [] }`. Supported platform keys are `LINKEDIN`, `NAUKRI`, `INDEED`, `INSTAHYRE`, `CUTSHORT`, and `HIRIST`. Sender addresses are required and validated. This does not connect a portal account.
- `PATCH /integrations/job-portals/{platform}/discovery` — JSON `{ "enabled": true | false }`. Enabling requires a configured sender and an active Gmail OAuth connection; otherwise returns 409. Direct portal source types remain disabled.
- `GET /integrations/job-portals/{platform}/history?limit=20` — recent collection runs for that user's alert source, including retry counts and sanitized error summaries.
- `GET /integrations/job-portals/audit?platform=LINKEDIN&offset=0&limit=50` — newest-first integration audit events, optionally filtered by one supported portal or `GMAIL`.

Gmail disconnect or failed refresh disables that user's enabled Gmail alert sources but retains their configuration and prior collection history. The existing `/integrations/gmail/reviews` queue handles messages that cannot be parsed safely. Every connection, configuration, and discovery toggle change is recorded in the integration-specific audit ledger; tokens remain encrypted in the existing Google OAuth connection model and are never exposed by these endpoints.

Gmail alert sources accept `configuration` with `platform` (`GENERIC`, `LINKEDIN`, `NAUKRI`, `INDEED`, `INSTAHYRE`, `CUTSHORT`, or `HIRIST`), required `allowed_senders`, optional `required_terms`, and optional Gmail `label_ids`. `GENERIC` parses only explicit alert fields and a real URL; portal adapters remain in the review queue until a sanitized representative sample is provided. Message IDs are deduplicated per source; incremental cursor and Gmail pagination state are stored in the source configuration. Unknown emails are retained in `gmail_alert_reviews` with a bounded excerpt for their owner. A manual source collection also retries up to 100 outstanding review messages per run. Existing career-page jobs and manual import flows are unchanged. Apply additive migration `a17f4c29d6b1` before enabling the Gmail review UI.

Duplicate registration returns 409. Invalid, expired, replayed, or revoked tokens return 401. Email and body validation errors return 422.

## Profile and preferences

All routes require `Authorization: Bearer <access_token>` and only access the authenticated user's records.

- `GET /profile` / `PUT /profile` — full name, current designation/company, experience months, notice period days, salary range, currency, and bio. PUT is a full replacement of these fields and rejects invalid ranges.
- `GET /preferences` / `PUT /preferences` — target roles, required/optional skills, minimum/maximum experience, salary range, locations, work modes, excluded companies/roles, employment types, and active status. PUT replaces the complete preference object.

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
- `POST /jobs/import` — manually import listing fields, optional required/preferred skills, experience/salary data, and a URL; the URL is validated and stored but never fetched by this endpoint. Exact source-scoped re-imports are idempotent.
- `GET /jobs/{job_id}` — get an owned job and provenance.
- `POST /jobs/{job_id}/refresh` — request collection for its source when a connector exists; manual and unsupported sources return 409.

Normalized job data includes title, company, location, work mode, description, apply URL, compensation and experience only when the source makes those values clear, skills, and provenance. Unknown salary/experience stays null. Cross-source duplicate candidates retain both records and are stored for review; records are not silently merged. Career page requests obey robots.txt, reject private/reserved destinations, do not follow redirects, and use bounded retries/rate limits. Gmail requires configured OAuth and an explicit sender allowlist. Portal scraping that requires login, bypasses anti-bot controls, or lacks an authorized API/feed is not implemented.

## Matching

All matching endpoints require authentication and use only the authenticated user's owned jobs and resume versions.

- `POST /matching/run` — match all owned active jobs (bounded by `MATCHING_MAX_BATCH`) or only `job_ids`; accepts `resume_version_id` and `include_ai`. If no version is supplied, the latest version of the selected default resume is used.
- `POST /matching/jobs/{job_id}` — match one owned job.
- `POST /matching/rematch` — rematch selected or all owned jobs with a chosen resume version. Identical input fingerprints return the existing result; changed resume, profile/preferences, job content, weights, model, prompt, or scoring version produces a new history row.
- `GET /matching/results` — filters: `min_score`, `location`, `work_mode`, `skill` (matched skill), `source_id`, `eligibility`, `recommendation`, and user-owned `review_status`, plus `offset`/`limit`.
- `GET /matching/results/{match_id}` — one owned result with job details, criterion scores, available/missing criteria, strengths, concerns, evidence, and explanation.
- `GET /matching/summary` — result counts, average score/confidence, eligibility, and recommendation totals.

`MATCHING_WEIGHTS` must contain exactly `skills`, `experience`, `role`, `location`, and `salary` with values totaling 100. The score renormalizes configured weights for available criteria only. Confidence is the share of configured weight that had sufficient data. Required skills count twice preferred skills in the skills criterion. Eligibility is `MATCH`, `PARTIAL_MATCH`, `MISMATCH`, or `UNKNOWN`; absent data is not treated as a mismatch. Known exclusions and preference conflicts remain hard mismatches regardless of AI output.

AI is enabled only when `MATCHING_AI_ENABLED=true` and `OPENAI_API_KEY` is configured. Structured Pydantic output is validated, exact citations must appear in supplied resume/job text, and claimed matched skills must be supported by resume evidence. Contact fields are excluded from the provider payload. Provider timeouts, one transient retry, a PostgreSQL per-user request limit, batch limits, an AI-call cap, and a concurrency semaphore bound cost. A deterministic result is persisted when AI is disabled or unavailable. Provider token usage, model name, prompt version, and scoring version are retained with the match.

## Dashboard, pipeline, interviews, follow-ups, and analytics (Phase 7)

All endpoints require a bearer access token and scope reads/writes to the authenticated user. Dates use ISO `YYYY-MM-DD`; date-only boundaries are interpreted in `Asia/Kolkata`. Pagination uses `offset` and bounded `limit`.

- `GET /dashboard/summary?start_date=&end_date=` — total owned jobs, new jobs in range, latest-per-job strong matches (AI `APPLY` recommendation or deterministic score >= 75, in either case without a hard mismatch), pending/approved reviews, current application-stage counts created in range, recent activity, recent matches, and upcoming items. Total discovered jobs is lifetime; `new_jobs` is date-filtered.
- `GET /dashboard/recent-activity?limit=` — newest actual review/application audit events.
- `GET /dashboard/upcoming?limit=` — upcoming scheduled interviews and pending follow-ups; overdue follow-ups include `overdue: true`.
- `GET /dashboard/pipeline` — paginated applications with `search`, `status`, `date_from`, `date_to` (submitted date), `location`, `work_mode`, and `sort_by=updated|created|company|title` filters.
- `GET /applications/{application_id}/timeline` — chronological existing application events, review history, and append-only audit events. No historical events are synthesized.
- `PATCH /applications/{application_id}/notes` — JSON `{ "notes": "..." }`; private notes are returned only to the owning user and changes are audited without storing the note contents in audit metadata.
- `GET /interviews?application_id=&status=&upcoming_only=&offset=&limit=` / `POST /interviews` / `GET /interviews/{interview_id}` / `PATCH /interviews/{interview_id}` / `DELETE /interviews/{interview_id}` — create/list/read/update/cancel. The list returns `{items,total,offset,limit}`. Create requires an owned `application_id`, an offset-aware `scheduled_at`, a valid IANA timezone (default Asia/Kolkata), and an HTTP(S) meeting URL if supplied. DELETE is a historical-preserving cancellation.
- `GET /follow-ups?application_id=&status=&overdue=&offset=&limit=` / `POST /follow-ups` / `PATCH /follow-ups/{follow_up_id}` / `DELETE /follow-ups/{follow_up_id}` — create/list/update/complete/cancel. The list returns `{items,total,offset,limit}`. `due_at` must be offset-aware; completion sets `completed_at`. DELETE cancels without erasing history.
- `GET /analytics/overview?start_date=&end_date=` — jobs collected, match-score distribution, application status/time counts, submitted-application interview/offer conversion, and application source counts.
- `GET /analytics/applications` and `GET /analytics/matches` — focused subsets of the overview metrics.

Conversion objects return `numerator`, `denominator`, and `percentage`; percentage is `null` until the submitted sample has at least five records. Denominators use application records with `submitted_at`, which is set only by Phase 6 explicit submission confirmation. No notification is sent in Phase 7.

## Phase 8 automation, notifications, and monitoring

All routes below require a bearer access token and return only the authenticated user's settings, notifications, source runs, and source metrics. The worker health snapshot contains operational status only; it omits credentials and private resume/profile content.

- `GET /automation/settings` / `PUT /automation/settings` — automation enabled flag, user timezone for quiet hours/reminders, email opt-in, notification category switches, minimum match score, quiet hours, and reminder intervals. The schedule itself is configured with `AUTOMATION_TIMEZONE`; its six-hour slots are 00:00, 06:00, 12:00, and 18:00.
- `GET /automation/status` — worker/scheduler status, heartbeat, last successful run, next scheduled run, and the current user's per-source success/partial/failure/retry/duration/matching metrics.
- `GET /automation/collection-runs?offset=&limit=` — paginated history of the authenticated user's source collection runs.
- `POST /automation/collect` with `{ "source_ids": [] }` — manually collect all enabled sources owned by the user; optionally provide a list of enabled owned source UUIDs. Connector errors remain isolated by source. This endpoint does not apply to jobs.
- `GET /monitoring` — the user's automation status and notification delivery summaries.
- `GET /notifications?unread_only=&offset=&limit=` — inbox with read state and email delivery state.
- `PATCH /notifications/{notification_id}/read` — mark one owned notification read; returns 404 for another user's notification.
- `GET /notifications/preferences` / `PUT /notifications/preferences` — aliases for user notification preferences.
- `GET /notifications/reminder-settings` — reminder timezone and lead intervals.
- `GET /notifications/delivery-history?offset=&limit=` — user-owned email delivery outcomes; error fields contain only exception type names.

The separate `worker` Compose service runs scheduled work under a PostgreSQL advisory lock. It records durable run keys and uses bounded per-source retries/timeouts. Matching uses Phase 5 fingerprint caching. Reminder/outbox processing is idempotent; email is sent only when SMTP is configured and the user opts in. No application form is submitted by this worker.

## Phase 8 database/test commands

```powershell
docker compose -p job-hunting-agent-p2verify --env-file .env exec backend python -m alembic upgrade head
docker compose -p job-hunting-agent-p2verify --env-file .env exec backend python -m alembic current
docker compose -p job-hunting-agent-p2verify --env-file .env --profile verification run --rm backend-test
cd frontend; npm test; npm run build
```

Status changes continue through `PATCH /applications/{application_id}/status` with server-validated transitions. That route rejects `READY_TO_APPLY` and `APPLIED`; only Phase 6 final approval and explicit manual submission confirmation can set those states.

## Migration commands

Run from `backend` after PostgreSQL is available and `.env` contains `POSTGRES_*` (or `DATABASE_URL`) settings:

```powershell
python -m alembic upgrade head
python -m alembic current
python -m alembic downgrade base  # destructive schema rollback; local/dev only
```

The initial revision includes all Phase 2 models, including auth refresh tokens. Phase 4 adds owned sources and normalized job metadata via `a7d91b2f4c30` and `b68e21c4a90f`. Phase 5 adds versioned match history, preference exclusions/employment types, and PostgreSQL request-limit counters in additive revision `c5198a0fd732`. API startup does not create or alter tables. Downgrading Phase 5 refuses when multiple match-history versions for one user/job cannot fit the earlier uniqueness constraint.

Phase 6 adds human-controlled review and application preparation in additive revision `d63fa8bc1201`. It extends the existing workflow tables and refuses downgrade if review audit events cannot fit the pre-Phase-6 schema.

## Job review and applications

Every endpoint below requires an authenticated bearer access token and scopes records to its owner. Job approval only permits preparation; it never approves submission.

### Job reviews

- `GET /job-reviews` — matched jobs with current review status, match score, skills, AI explanation, and review history. A pending review record is created for a previously unreviewed match.
- `POST /job-reviews/{job_id}/approve` — set `APPROVED_FOR_PREPARATION`.
- `POST /job-reviews/{job_id}/save` — set `SAVED`.
- `POST /job-reviews/{job_id}/reject` — JSON `{ "reason": "optional" }`; set `REJECTED` and preserve the reason in review history.

### Application preparation and tracking

- `GET /applications` — list owned applications.
- `POST /applications` — JSON `{job_id, resume_version_id, job_match_id}`; requires an approved job review and owned records. A unique owner/job constraint prevents duplicates.
- `GET /applications/{application_id}` — application and job details.
- `PATCH /applications/{application_id}/status` — JSON `{ "status": "..." }` for allowed tracking transitions. `READY_TO_APPLY` and `APPLIED` cannot be set here.
- `GET /applications/tracking` — applications with audit timelines.
- `GET /applications/{application_id}/audit` — ordered, append-only audit events.

### AI drafts and exact-version approvals

- `POST /applications/{application_id}/generate` — JSON `{draft_types?: [...], user_context?: {...}}`; prepares `TAILORED_RESUME`, `COVER_LETTER`, `RECRUITER_MESSAGE`, and/or `APPLICATION_ANSWERS`.
- `POST /applications/{application_id}/regenerate` — same request, creates new versions and preserves old versions.
- `GET /applications/{application_id}/drafts` — list version history; optional `draft_type` filter.
- `GET /applications/{application_id}/drafts/{draft_id}` — read one version.
- `PATCH /applications/{application_id}/drafts/{draft_id}` — JSON `{ "body": "user-edited content" }`; creates a new version and invalidates affected approval.
- `POST /applications/{application_id}/drafts/{draft_id}/approve` — approve the exact draft version.

Generation requires `OPENAI_API_KEY`; otherwise it returns 503. A PostgreSQL per-user daily limit (`APPLICATION_GENERATION_DAILY_LIMIT`, default 10 draft generations) and request timeout bound provider use. Structured responses cite exact resume and job excerpts; prompts treat both sources as untrusted. Resume contact fields are not sent. Missing salary, notice, availability, work authorization, and relocation answers are added as `[USER INPUT REQUIRED]` unless the user supplied them in `user_context`. Generated text remains untrusted until a user approves its version.

### Checklist, final approval, and manual handoff

- `GET /applications/{application_id}/checklist` / `PUT /applications/{application_id}/checklist` — read or update `{ "items": {"job_details_verified": {"completed": true}, ...} }`. The required keys are job details, company, application URL, selected resume, tailored resume, cover letter, application answers, expected salary, notice period, and personal information. A not-applicable item requires a reason.
- `POST /applications/{application_id}/final-approval` — JSON `{ "confirmed": true }`; revalidates checklist, current draft approvals, job review, and verified HTTPS application URL. Records the approving user, timestamp, exact version IDs, and checklist snapshot, then sets `READY_TO_APPLY`.
- `POST /applications/{application_id}/open-url` — records the URL handoff and returns the original HTTPS application URL plus a manual-review reminder. It does not change the application status.
- `POST /applications/{application_id}/confirm-submission` — JSON `{ "submitted": true, "notes": "optional" }`; only this explicit confirmation after final approval sets `APPLIED` and `submitted_at`.

The API does not fetch the handoff URL, fill forms, click Submit, automate login, or handle CAPTCHA. PostgreSQL rejects updates and deletes to audit rows. Audit metadata excludes secrets and records only a boolean when a submission note was provided.
