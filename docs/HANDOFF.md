# Facebook Ad Builder - Handoff Guide

## What This Repo Contains

Production-ready Facebook ad workflow app with:

- Competitor ad research (Facebook Ad Library + scraper fallback)
- AI copy generation (Gemini)
- AI image generation (Kie.ai primary, Fal.ai optional fallback)
- Ad/campaign management endpoints

## Key Fixes Included

- Replaced Fal-only image generation path with provider abstraction.
- Added Kie task workflow support (`createTask` + `recordInfo`) for:
  - `google/nano-banana`
  - `google/nano-banana-edit`
  - `google/imagen4`
- Added bounded concurrency/retry controls for image generation.
- Removed silent placeholder fallback in live mode.
- Added unit tests for provider/model mapping and URL extraction.

## Security Guarantees For This Handoff

- No real API keys are committed.
- Runtime secrets must be provided via local env files.
- `.env`, `.env.local`, and `.env.*.local` are ignored.
- `backend/uploads/*` is ignored (except `.gitkeep`) so generated assets are not committed.

## Required Environment Variables

Use `.env.example` as template. Minimum required values:

- `DATABASE_URL`
- `SECRET_KEY`
- `GEMINI_API_KEY`
- `KIE_AI_API_KEY` (recommended) or `FAL_AI_API_KEY`

Recommended for Kie path:

- `IMAGE_PROVIDER=kie`
- `KIE_API_BASE_URL=https://api.kie.ai`
- `IMAGE_GEN_MAX_CONCURRENCY=5`
- `IMAGE_GEN_RETRY_ATTEMPTS=2`
- `KIE_POLL_INTERVAL_SECONDS=2`
- `KIE_MAX_POLL_ATTEMPTS=90`

## Local Run (Fast)

1. Start PostgreSQL (local or Docker).
2. Copy env template:
   - `cp .env.example .env.local`
   - `cp .env.local backend/.env`
3. Backend:
   - `cd backend`
   - `python3 -m venv .venv && source .venv/bin/activate`
   - `pip install -r requirements.txt`
   - `python init_db.py`
   - `uvicorn app.main:app --reload --port 8000`
4. Frontend:
   - `cd frontend`
   - `npm install`
   - `npm run dev`
5. Open:
   - `http://localhost:5173`

## API Smoke Test

1. Login:
   - `POST /api/v1/auth/login/json`
2. Generate image:
   - `POST /api/v1/generated-ads/generate-image`
3. Expect:
   - JSON response with `images[0].url`

## Scale Testing Notes

- Test result sample: 10 requests, concurrency 5, 100% success.
- Track:
  - success/failure rate
  - p50/p95 latency
  - provider credit usage
- Increase concurrency gradually and watch 429/timeouts.

## Suggested Next Hardening Steps

- Add async job queue (Celery/RQ) for large batches.
- Add provider metrics dashboards (latency, failure reason, credit burn).
- Add circuit breaker + fallback policy per provider.
- Add webhook receiver mode for Kie task completion (reduce polling load).
