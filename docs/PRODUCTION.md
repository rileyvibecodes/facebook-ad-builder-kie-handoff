# Production Deployment Reference

Last updated: 2026-03-03

## Live URLs

| Service | URL |
|---------|-----|
| Frontend | https://frontend-skillstack.vercel.app |
| Backend API | https://backend-production-78c0.up.railway.app |
| API Docs (Swagger) | https://backend-production-78c0.up.railway.app/api/v1/docs |
| Health Check | https://backend-production-78c0.up.railway.app/health |

## Architecture

```
┌──────────────────────────┐        ┌──────────────────────────────────────┐
│       Vercel              │        │            Railway                    │
│                          │        │                                      │
│  frontend/               │  CORS  │  backend/Dockerfile                  │
│  React 19 + Vite         │───────>│  FastAPI + Uvicorn                   │
│  Static SPA              │        │                                      │
│                          │        │         │                            │
│  Root dir: frontend/     │        │         │ internal networking        │
│  Framework: Vite         │        │         v                            │
│  Auto-deploy: GitHub     │        │  PostgreSQL 16                       │
│                          │        │  postgres.railway.internal:5432      │
│  Env:                    │        │  Persistent volume mounted           │
│  VITE_API_URL=<backend>  │        │                                      │
└──────────────────────────┘        └──────────────────────────────────────┘
```

**Frontend (Vercel)** serves the React SPA. All API calls go to the Railway backend via `VITE_API_URL` (baked in at build time).

**Backend (Railway)** runs FastAPI in a Docker container. Connects to Postgres over Railway's internal network (`postgres.railway.internal`).

**Database (Railway)** is PostgreSQL 16 with a persistent volume at `/var/lib/postgresql/data`.

## Auto-Deploy

Both services auto-deploy on push to `main`:

| Service | Trigger | Build |
|---------|---------|-------|
| Frontend | Push to `main` (Vercel watches `frontend/` root) | `npm run build` via Vite |
| Backend | Push to `main` (Railway watches repo) | `backend/Dockerfile` |

Backend start command on every deploy:
```
sh -c 'alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}'
```

This runs pending Alembic migrations before starting the server.

## Environment Variables

### Backend (Railway)

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string (internal Railway networking) |
| `SECRET_KEY` | JWT signing key (auto-generated, 32-byte URL-safe) |
| `GEMINI_API_KEY` | Google Gemini API for copy generation |
| `KIE_AI_API_KEY` | Kie.ai API for image generation |
| `KIE_API_BASE_URL` | `https://api.kie.ai` |
| `IMAGE_PROVIDER` | `kie` |
| `IMAGE_GEN_MAX_CONCURRENCY` | `5` |
| `IMAGE_GEN_RETRY_ATTEMPTS` | `2` |
| `IMAGE_GEN_TIMEOUT_SECONDS` | `120` |
| `KIE_POLL_INTERVAL_SECONDS` | `2` |
| `KIE_MAX_POLL_ATTEMPTS` | `90` |
| `ENABLE_IMAGE_GEN_MOCK` | `false` |
| `ALLOWED_ORIGINS` | Comma-separated Vercel frontend domains |
| `ADMIN_EMAIL` | Admin superuser email |
| `ADMIN_PASSWORD` | Admin superuser password |

To view or change these: Railway dashboard > fb-ad-builder project > backend service > Variables tab.

### Frontend (Vercel)

| Variable | Purpose |
|----------|---------|
| `VITE_API_URL` | `https://backend-production-78c0.up.railway.app/api/v1` |

To view or change: Vercel dashboard > frontend project > Settings > Environment Variables.

**Important:** `VITE_API_URL` is baked into the JS bundle at build time. Changing it requires a redeploy.

## Database

- **Engine:** PostgreSQL 16.12
- **Host:** `postgres.railway.internal:5432` (internal only, not publicly accessible)
- **Database name:** `fb_ad_builder`
- **Schema management:** Alembic migrations run on every deploy
- **Initial setup:** `init_db.py` creates tables via `Base.metadata.create_all`, seeds roles/permissions, and creates the admin superuser

### Roles and Permissions

The database is seeded with four roles:

| Role | Access |
|------|--------|
| `admin` | Full access to all resources |
| `manager` | Brands, products, ads, campaigns, templates (read/write) |
| `editor` | Read brands/products, write ads/templates |
| `viewer` | Read-only access |

### Adding Migrations

```bash
cd backend
alembic revision --autogenerate -m "describe change"
git add alembic/versions/
git commit && git push  # Auto-deploys and runs migration
```

## Authentication

- JWT-based with access + refresh tokens
- Access token expires in 30 minutes (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`)
- Refresh token expires in 7 days (configurable via `REFRESH_TOKEN_EXPIRE_DAYS`)
- Login endpoint: `POST /api/v1/auth/login` (OAuth2 form data: `username` + `password`)
- Register endpoint: `POST /api/v1/auth/register` (requires authentication, admin creates users)

## CORS

Backend allows requests from origins listed in `ALLOWED_ORIGINS` env var (comma-separated) plus `localhost` defaults for dev.

If you add a custom domain to Vercel, add it to `ALLOWED_ORIGINS` on Railway and redeploy the backend.

## Health Monitoring

Backend exposes `GET /health` which returns `{"status": "healthy"}`. Railway uses this as a healthcheck with a 100-second timeout.

On startup, the backend validates the PostgreSQL connection and logs the database version. If the connection fails, the service exits with an error.

## Custom Domain Setup

### Frontend (Vercel)

1. Go to Vercel dashboard > frontend project > Settings > Domains
2. Add your domain
3. Configure DNS: CNAME to `cname.vercel-dns.com`
4. Add the new domain to Railway's `ALLOWED_ORIGINS` env var
5. Redeploy backend on Railway to pick up the CORS change

### Backend (Railway)

1. Go to Railway dashboard > backend service > Settings > Networking
2. Add custom domain
3. Configure DNS as shown
4. Update `VITE_API_URL` on Vercel to the new domain
5. Redeploy frontend on Vercel to bake in the new URL

## Troubleshooting

### Backend won't start

**"DATABASE_URL environment variable is required"**
- Check Railway Variables tab for the backend service

**"SECRET_KEY environment variable is required"**
- Set `SECRET_KEY` in Railway Variables (generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`)

**Alembic migration fails on deploy**
- Check Railway deploy logs for the specific error
- If a migration references a table that doesn't exist, you may need to run `init_db.py` first
- To run one-off commands: temporarily change start command in Railway Settings, deploy, then revert

### Frontend shows blank page or API errors

**CORS errors in browser console**
- Verify `ALLOWED_ORIGINS` on Railway includes your Vercel domain (with `https://`)
- Redeploy backend after changing `ALLOWED_ORIGINS`

**API calls going to localhost**
- `VITE_API_URL` was not set at build time. Check Vercel env vars and redeploy

### Database issues

**"relation does not exist"**
- Tables were not created. Temporarily set start command to `sh -c 'python init_db.py && alembic stamp head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}'`, deploy once, then revert to the standard start command

**Connection refused**
- Check that the Postgres service is running on Railway
- Verify `DATABASE_URL` uses `postgres.railway.internal` (not a public URL)

## Operational Runbooks

### Rotate SECRET_KEY

1. Generate new key: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Update `SECRET_KEY` in Railway backend variables
3. Redeploy backend
4. All existing JWTs are invalidated; users must re-login

### Reset admin password

1. Update `ADMIN_PASSWORD` in Railway backend variables
2. Temporarily change start command to: `sh -c 'python init_db.py && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}'`
3. Deploy (init_db.py skips if user exists, but create_superuser checks by email)
4. To force reset: connect to Postgres directly and update the hashed_password, or delete the user and re-run init_db.py

### View logs

- **Backend (Railway):** Railway dashboard > backend service > Deployments > click deployment > View Logs
- **Frontend (Vercel):** `vercel logs frontend-skillstack.vercel.app` or Vercel dashboard > frontend > Deployments

### Force redeploy

- **Backend:** Railway dashboard > backend service > Deployments > Redeploy, or push an empty commit
- **Frontend:** `cd frontend && vercel deploy --prod --yes`, or push a commit touching `frontend/`
