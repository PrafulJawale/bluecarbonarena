# Deployment
Frontend static/Vercel/Netlify/Nginx, backend on Render/Railway/Fly/VM, PostgreSQL (enable PostGIS for production geometry), set DATABASE_URL, SECRET_KEY, CORS_ORIGINS to public frontend origin, VITE_API_URL to public backend, persistent object storage (S3) replacing local uploads adapter. Use `docker compose up --build`.
