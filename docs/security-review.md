# Security review

Review scope: Phase 9 source review and PostgreSQL-backed API verification for Phases 1–8. No external production deployment was performed.

## Controls verified

- Passwords use Argon2 through `pwdlib` when available (scrypt fallback); plaintext passwords are not persisted. Login responses avoid distinguishing unknown, inactive, or incorrect-password accounts.
- Access and refresh tokens are signed JWTs with type and expiry claims. Refresh tokens are persisted only as SHA-256 digests, rotated on refresh, and revoked by family on replay/logout. Access tokens remain valid until their short configured expiry.
- Failed logins are limited in PostgreSQL by a SHA-256 fingerprint derived from the JWT secret, client address, and normalized email. Raw email and IP are not stored in the throttle table. Configure the limit and fixed-window duration via `AUTH_LOGIN_MAX_ATTEMPTS` and `AUTH_LOGIN_WINDOW_MINUTES`.
- `APP_ENV=production` validates non-development JWT and database credentials, HTTPS-only explicit CORS origins, and paired SMTP credentials. Interactive API docs are disabled in production mode.
- API data access is authenticated and user-scoped. Resume files use private storage, opaque keys, bounded streaming uploads, type checks, and ownership checks. AI-generated content is treated as untrusted and does not submit applications.
- Compose backend, worker, and frontend enable `no-new-privileges` and drop Linux capabilities. Frontend container uses the Node non-root user.
- `.env` is ignored by Git; `.env.example` contains placeholders. Do not commit real credentials or uploaded files.

## Findings and residual risk

| Severity | Finding | Status / action |
| --- | --- | --- |
| High before production configuration | Development JWT and PostgreSQL defaults are unsuitable for deployment. | Production settings now reject known defaults. Set unique secrets and verify the effective environment before starting. |
| Medium | Compose exposes development API, Vite, and PostgreSQL host ports and has no TLS reverse proxy. | Do not expose this Compose configuration to the public internet. Restrict host firewall access; deploy behind a reviewed TLS proxy with private database networking. |
| Medium | Browser access tokens are held in `sessionStorage`; an XSS bug could read them. | React escapes ordinary text and no dangerous HTML rendering was found in reviewed frontend code. Add a CSP and consider an HttpOnly cookie/BFF design before public deployment. |
| Medium (development tooling) | Full `npm audit` reports 7 moderate findings through the ESLint TypeScript parser's transitive `minimatch` dependency. `npm audit fix` cannot resolve it without a forced dependency change. | `npm audit --omit=dev` reports zero vulnerabilities. Keep the toolchain out of runtime images and update it when a compatible upstream fix is available; do not use `--force` without checking breaking changes. |
| Low | Backend and worker run as root in the existing runtime image to preserve compatibility with the preexisting resume volume ownership. | Capabilities are dropped and privilege escalation is disabled. Validate volume ownership and adopt a fixed non-root UID before production. |
| Low | Frontend TypeScript lint currently reports 38 `any` warnings. | No lint errors; gradually replace untyped API/test values with explicit types. |
| Informational | External job sites, SMTP delivery, OpenAI, and OAuth integrations depend on provider credentials and were not live-tested. | See known limitations; test each integration using authorized sandbox accounts before enablement. |

No critical unresolved application-logic vulnerability was identified in the reviewed Phase 9 scope. This is an engineering review, not a penetration test or compliance certification.
