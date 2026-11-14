# Requirements baseline

## Product objective

Personal platform to discover relevant roles, compare them with a verified resume and stated preferences, prepare application materials, and track outcomes. Every opportunity and every application package requires human review. The user submits applications manually; opening an application URL must never imply that a submission occurred.

## Initial profile defaults

Seed preferences are configurable: 2–3 years' experience; Python backend, FastAPI, generative AI/LLM/RAG, and Python/React full stack roles; Chennai, remote India, or hybrid Chennai; INR 12–15 LPA. Skills include Python, FastAPI, Flask, Django, React, Node, PostgreSQL, MySQL, Redis, Docker, OpenAI, Gemini, LangChain, LlamaIndex, Qdrant, RAG, LLM integration, and prompt engineering. Missing personal information is never inferred.

## Functional scope

- Account, profile, and preference management.
- Private resume upload, extraction, parsing, versions, and primary selection.
- Independent connectors for authorized sources; per-source status and failure isolation.
- Normalization, deduplication, expiry detection, matching, company research, and suspicious listing indicators.
- Resume and cover-letter drafts that preserve factual accuracy.
- Separate job review, content approval, and manual submission confirmation checkpoints.
- Application tracking, notifications, collection history, and analytics.

## Quality and security requirements

Use a modular monolith, PostgreSQL, UUID keys, UTC timestamps, ownership checks, validated uploads, environment secrets, audit events, idempotent operations, rate limiting, and safe logging. Treat job descriptions and email as untrusted content. Do not bypass source access controls, CAPTCHAs, rate limits, or anti-bot mechanisms. Unknown salary is not zero. LLM output is schema validated.

## Phase 1 acceptance

Architecture and implementation plan documented; initial Docker Compose with persistent PostgreSQL; environment template; FastAPI liveness endpoint; responsive React/Vite shell; README with commands. Future workflow behavior is explicitly out of scope.
