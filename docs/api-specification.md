# API specification

Base prefix: `/api/v1`. Phase 1 exposes only `GET /health`, returning `{"status":"ok"}` for process liveness. It does not query PostgreSQL and does not imply readiness.

Planned route groups:

- Authentication: `/auth/register`, `/auth/login`, `/auth/me`
- Profile and preferences: `/profile`, `/preferences`
- Resumes: `/resumes`, `/resumes/upload`, `/resumes/{id}/parse`
- Jobs and sources: `/jobs`, `/jobs/recommended`, `/jobs/collect`, `/sources`
- Review: `/job-reviews` and per-job approve/reject/save actions
- AI assistance: match, tailor resume, recruiter message, interview preparation
- Applications: preparation, drafts, final approval, open URL, explicit submission confirmation
- Dashboard: summary, trends, collection runs, notifications

Protected routes will enforce user ownership, use Pydantic request/response schemas, return standard HTTP status codes, and avoid exposing secrets or personal information in logs. Opening a URL is not a submission event. Routes will be added with their corresponding phase rather than returning placeholder data.
