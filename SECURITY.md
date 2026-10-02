# Security Policy

WEAVIA is a hackathon prototype with no accounts, payments or personal data. The API is read-only.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting (repository **Security** tab, **Report a vulnerability**). Do not open a public issue for a security problem. If that option is unavailable, open a public issue that says only "security contact requested", with no details.

Please include what you found, how to reproduce it, and the affected file or route.

## Built-in protections

- Per-client rate limiting on the API, with a stricter limit on `POST /api/v1/lab/simulate` (see [docs/API.md](docs/API.md)).
- Security headers on API and web responses (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).
- Input validation on every parameter (422 on invalid values).
- No secrets in the repository. `.env` files are gitignored. Only `.env.example` is committed.

## Known limits

- The rate limiter is in-memory and per process. It is not a distributed limiter.
- `WEAVIA_CORS` defaults to `*` for local development. **Restrict it before any public deployment.**
- No Content-Security-Policy is set yet.
