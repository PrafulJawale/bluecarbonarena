# BLUECARBON ARENA
Full-stack blue carbon project management, evidence verification, deterministic illustrative carbon calculations, simulated credit issuance and marketplace.

> Scientific integrity: not an accredited registry. Demo credits are simulated; illustrative factors are not official emission factors.

## Stack
React+TypeScript+Vite+Tailwind+Leaflet+Recharts / FastAPI+SQLAlchemy+Pydantic / SQLite (dev) or PostgreSQL (prod via Docker Compose) / Argon2id + JWT / Pytest.

## Quick start
```bash
# backend
python3 -m venv /tmp/venv && /tmp/venv/bin/pip install -r backend/requirements.txt
cd backend && /tmp/venv/bin/python seed.py && /tmp/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
# frontend (new terminal)
cd frontend && npm install && npm run dev
```
Frontend http://localhost:5173 · API http://localhost:8000/docs · Health `/api/v1/health`

Demo accounts (password `DemoPass123!`): admin@, verifier@, developer@, researcher@, buyer@, community@bluecarbonarena.local

## Tests
`DATABASE_URL=sqlite:///./test_bca.db /tmp/venv/bin/python -m pytest backend/tests -q` and `cd frontend && npm run build`

## Docker
Copy `.env.example` to `.env`, adjust, `docker compose up --build` (not executed in sandbox — no Docker available).

Docs: `docs/` — Architecture, Schema, API, Security, Methodology, Testing, Deployment, Presentation Guide.
Known limitations: JWT in localStorage (demo), local file storage, GeoJSON-in-JSON instead of native PostGIS, no real payments, Playwright E2E not run.
