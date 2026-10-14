# Architecture
```mermaid
flowchart LR
 UI[React SPA]-->API[FastAPI /api/v1]-->DB[(SQLite dev / PostgreSQL+PostGIS-ready prod)]
 API-->FS[Local uploads adapter]
```
Service boundaries: routes in `app/main.py`, calculation in `app/calc.py`, auth in `app/security.py`, models in `app/models.py`. Geometry stored as GeoJSON JSON + lat/lon for SQLite portability; production can migrate boundary to PostGIS geometry (documented limitation).
