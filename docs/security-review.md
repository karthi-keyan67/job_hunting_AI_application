# Security review

Review scope: Phase 10 source review, PostgreSQL regression, production-image, and localhost HTTPS verification for Phases 1–9. No public deployment or live third-party credential flow was performed.

## Controls verified

- Passwords use Argon2 through `pwdlib` when available (scrypt fallback); plaintext passwords are not persisted. Login responses avoid distinguishing unknown, inactive, or incorrect-password accounts.
- Access and refresh tokens are signed JWTs with type and expiry claims. Refresh tokens are persisted only as SHA-256 digests, rotated on refresh, and revoked by family on replay/logout. Access tokens remain valid until their short configured expiry.
- Failed logins are limited in PostgreSQL by a SHA-256 fingerprint derived from the JWT secret, client address, and normalized email. Raw email and IP are not stored in the throttle table. Configure the limit and fixed-window duration via `AUTH_LOGIN_MAX_ATTEMPTS` and `AUTH_LOGIN_WINDOW_MINUTES`.
- `APP_ENV=production` validates non-development JWT and database credentials, HTTPS-only explicit CORS origins, and paired SMTP credentials. Interactive API docs are disabled in production mode.
- API data access is authenticated and user-scoped. Resume files use private storage, opaque keys, bounded streaming uploads, type checks, and ownership checks. AI-generated content is treated as untrusted and does not submit applications.
- The separate production profile runs backend and worker as UID 10001 and frontend as Node UID 1000. PostgreSQL has no published host port; only Caddy is bound to loopback host ports. Production app credentials are mounted as Docker secret files and read by settings without logging values.
- Production static frontend emits CSP, X-Content-Type-Options, Referrer-Policy, X-Frame-Options, and Permissions-Policy. Caddy terminates TLS and adds HSTS plus the same defensive headers. A localhost HTTPS request verified the resulting headers; a public certificate was not requested.
- Production services configure health checks, restart policies, bounded CPU/memory, `init`, stop grace periods, `no-new-privileges`, and dropped Linux capabilities. Production resume storage uses a new volume, so the existing development resume volume was not changed.
- `npm audit` and `npm audit --omit=dev` report zero vulnerabilities after a scoped `minimatch@11.0.8` override. Ruff checks pass after fixing unused imports/style and adding type-checking-only ORM relationship imports.
- `.env` is ignored by Git; `.env.example` contains placeholders. Do not commit real credentials or uploaded files.

## Findings and residual risk

| Severity | Finding | Status / action |
| --- | --- | --- |
| High before production configuration | Development JWT and PostgreSQL defaults are unsuitable for deployment. | Production settings now reject known defaults. Set unique secrets and verify the effective environment before starting. |
| High before deployment | The development Compose profile exposes API/Vite/PostgreSQL ports and runs backend/worker as root. | Retained for local development. Use the separate production profile; it publishes no database port and uses non-root runtime images. Do not start the public profile until credentials/domain/network are configured and reviewed. |
| Medium | Browser access tokens remain in `sessionStorage`; active-token theft is possible if script injection occurs. | CSP restricts scripts to same-origin and React renders ordinary text safely. The client does not use cookies, so no partial cookie migration/CSRF behavior was introduced. Move to a complete HttpOnly refresh-cookie/session design before public launch. |
| Medium / blocked | Server-side Gmail OAuth and read-only connector are implemented, but no OAuth client credentials are configured and provider authorization has not been live-tested. | Credentials are encrypted at rest; state is one-use and hashed. Keep Gmail disabled until a configured Google OAuth client passes controlled live verification. |
| Medium / blocked | OpenAI key, SMTP configuration, and a controlled recipient are absent. | Deterministic matching and mocked provider-failure/outbox tests pass. No live OpenAI or SMTP request was made. |
| Low | Frontend ESLint exits successfully but reports 38 explicit-`any` warnings. | Replace the remaining untyped values incrementally; these are warnings rather than lint errors. |
| Informational | No owned public domain, public certificate issuance, or authorized production job-source account was available. | Caddy syntax and localhost TLS/headers were verified. Public ACME and live source collection remain unverified. |

The production profile is a hardening baseline, not a deployment approval. This review is not a penetration test or compliance certification. See [deployment-guide.md](deployment-guide.md) and [known-limitations.md](known-limitations.md) for the required prelaunch actions.
