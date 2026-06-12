# 04 — Deployment

How to host ScoutIQ. Three pieces: Postgres is already cloud-hosted (Neon), so a deploy
is just the FastAPI backend plus the Next.js frontend.

```
Vercel (frontend)  ──NEXT_PUBLIC_API_URL──▶  Railway/Render (FastAPI)  ──DATABASE_URL──▶  Neon (Postgres)
```

Production never calls LLMs: Sonar/Claude backfills and the eval CLI are offline scripts,
and the API serves cached DB rows and committed artifacts. The one scoped exception is the
rationale endpoint, which stays disabled unless you set its keys. There is no Redis or other
runtime dependency.

## What ships with the repo (no build-time surprises)

- `backend/scoutiq/model/artifacts/model.joblib` (1.8 MB) is committed — the API serves
  valuations without a training step. After a retrain, commit the new artifact and redeploy.
- `backend/Procfile` declares the web process; `backend/.python-version` pins Python 3.10.
- All serving dependencies are declared in `backend/pyproject.toml` (`pip install .`).

## Backend — Railway (or Render)

1. New project → **Deploy from GitHub repo**.
2. Set **root directory** to `backend`. The Procfile supplies the start command:
   `uvicorn scoutiq.api.main:app --host 0.0.0.0 --port $PORT`.
3. Environment variables:

   | var | value |
   |---|---|
   | `DATABASE_URL` | the Neon connection string (`postgresql+psycopg://…?sslmode=require`) |
   | `CORS_ORIGINS` | `http://localhost:3000,https://<your-app>.vercel.app` |

4. Health check path: `/health` (also reports the current season the UI badge reads).

Render's free tier works identically (root dir `backend`, same env vars) but spins down on
idle — first hit after sleep waits ~30–60 s. Railway's ~$5 hobby plan stays warm; pick per
audience. Note the first valuation request after any boot loads `model.joblib` into a
module-level singleton, so the very first watchlist call does a little extra work.

## Frontend — Vercel

1. Import the repo → set **root directory** to `frontend` (Next.js auto-detected).
2. Environment variable: `NEXT_PUBLIC_API_URL=https://<your-backend-host>` — the only
   frontend config; unset it and the app targets `http://localhost:8000` for local dev.
3. Deploy. Pushes to `main` auto-deploy from then on.

If you use Vercel preview deployments and want them to reach the API, append the preview
origin (or your stable preview alias) to `CORS_ORIGINS` on the backend.

## Operational notes

- **Data refreshes need no deploy.** ETL/backfills run locally against the same Neon DB,
  so new contracts/stats/scout reports appear in production immediately. Only a model
  retrain (new `model.joblib`) or code change requires a push.
- **Headshot cache is ephemeral.** The headshot proxy caches to local disk; platform
  restarts clear it and it re-fetches lazily. Harmless.
- **Keys stay local.** `PERPLEXITY_API_KEY`/`ANTHROPIC_API_KEY` are for offline scripts;
  set them in production only if you deliberately want the live rationale endpoint.
- **Neon free tier** is comfortable here: production traffic is read-mostly with small
  result sets, and writes happen from your machine.
