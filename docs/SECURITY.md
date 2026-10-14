# Security
Argon2id password hashing, JWT bearer (short-lived, stored in localStorage for this demo SPA — production should prefer HttpOnly secure cookies + CSRF), server-side RBAC + ownership checks, CORS allowlist, upload type/size checks + SHA-256 + random stored names, no secrets in repo, audit logs exclude passwords/tokens. Rate limiting & cookie migration are production hardening items.
