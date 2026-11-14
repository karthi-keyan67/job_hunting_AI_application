# Known limitations

- The current Docker Compose configuration is for local development/verification. Vite dev server, directly exposed host ports, and missing TLS/reverse proxy mean it is not ready for public deployment.
- The backend and worker still run as root to retain compatibility with the existing resume data volume. Compose drops capabilities and disables privilege escalation; a fixed non-root runtime UID remains a deployment task.
- The frontend stores access and refresh token response data in `sessionStorage`, and current UI flows do not automatically refresh access tokens. API sessions can expire and require signing in again. A cookie/BFF approach and CSP are recommended before external exposure.
- Frontend lint reports 38 explicit `any` warnings across existing Phase 6–8 UI and tests. Lint has no errors; warnings remain technical debt.
- `npm audit --omit=dev` reports no production dependency vulnerabilities. Full `npm audit` reports 7 moderate findings in the development-only TypeScript ESLint/minimatch dependency chain; the compatible audit fix did not resolve them, and npm's suggested forced change is potentially breaking.
- Ruff's first full backend app/test run reports 44 findings: model forward-reference strings flagged as undefined, unused imports, and a small number of formatting/style findings. Backend tests pass; clean up or configure a repository-wide lint baseline before treating Ruff as a CI gate.
- Access tokens are not individually revoked at logout; they expire according to `ACCESS_TOKEN_MINUTES`. Logout revokes the refresh-token family.
- Production settings validate secrets, CORS, and paired SMTP credentials, but this does not replace secret management, TLS, firewall rules, backups, monitoring, penetration testing, or deployment review.
- SMTP, OpenAI, Gmail OAuth, and live external job connectors require user/provider configuration. They were not validated against live external services in Phase 9.
- OCR for scanned resumes, automated application submission, and unsupported/private job-board scraping remain out of scope by design.
