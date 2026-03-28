# MLB Forecast V2

`MLB Forecast` is a split application:

- A `Python + FastAPI` backend for MLB data ingestion, Bayesian model fitting in `PyMC`, posterior storage, and season simulation.
- A `React + D3` frontend for customizable interactive visualizations and dashboard views.

## Architecture

```text
data_source/mlb_api.py
data_source/pitcher_stats.py   (starting pitcher quality, cached)
data_source/game_features.py   (rest, momentum, division flag)
        -> backend/app/services/modeling.py
        -> backend/app/services/dashboard.py
        -> backend/app/main.py
        -> frontend/src/*
```

## Backend

The backend exposes:

- `GET /api/health`
- `GET /api/teams`
- `GET /api/dashboard?team=Toronto+Blue+Jays&season=2026`

Core responsibilities:

- fetch and normalize MLB schedule/results data
- fit or load a hierarchical Poisson model
- store posterior sample snapshots under `.cache/posteriors`
- run posterior-driven forward simulations
- return frontend-friendly dashboard payloads

## Frontend

The frontend uses `React`, `TypeScript`, and `D3` to render:

- team spotlight metrics
- playoff odds bars
- offense and defense ranking bars
- division trajectory lines
- posterior density views
- projected standings sections

## Local Development

### 1. Install backend dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional tests (API smoke + data helpers):

```bash
pip install -r requirements-dev.txt
pytest
```

Full dashboard e2e (MLB API + fit or load posterior; slow on a cold cache):

```bash
MLB_RUN_INTEGRATION=1 pytest tests/test_smoke.py::test_api_dashboard_no_refit -q
```

Walk-forward benchmark (many MCMC fits):

```bash
python scripts/benchmark_full_model.py
```

### 2. Run the backend

```bash
uvicorn backend.app.main:app --reload
```

### 3. Install frontend dependencies

```bash
cd frontend
npm install
```

### 4. Run the frontend

```bash
cd frontend
npm run dev
```

The frontend expects the API at `http://localhost:8000`.

## Scheduled refresh (live app)

The app separates **daily actuals refresh** (fast, updates game scores) from
**weekly model refit** (slow, re-estimates team strengths via MCMC).

### Admin endpoints

| Endpoint | Method | Purpose | Speed |
|----------|--------|---------|-------|
| `/api/admin/refresh-actuals` | POST | Clear caches, re-fetch scores from MLB API | ~30 s |
| `/api/admin/refit-model` | POST | Full MCMC refit with fresh data | ~3–15 min |

Both accept an optional `?season=` query parameter (see `MLB_SEASON` below).

### Production environment

| Variable | Purpose |
|----------|---------|
| `ADMIN_API_KEY` | If set, both admin routes require header `X-Admin-Key: <value>`. **Set this on any public deployment.** |
| `CORS_ORIGINS` | Comma-separated list of allowed browser origins (e.g. `https://app.example.com`). Defaults to local Vite URLs. |
| `MLB_SEASON` | Default season for API query defaults (e.g. `2026`). |

### Helper script (cron / VPS)

From the repo root (set `API_BASE_URL` to your public API in production):

```bash
export API_BASE_URL=https://your-api.example.com
export ADMIN_API_KEY=your-secret   # if the server has ADMIN_API_KEY set
./scripts/call_admin.sh refresh    # daily
./scripts/call_admin.sh refit      # weekly
```

Optional: `MLB_SEASON=2026`, `CURL_MAX_TIME=900` for long refits.

### GitHub Actions (no server cron)

Workflows in `.github/workflows/` call your deployed API on a schedule.

1. **Secrets** (UI or CLI):
   - `API_BASE_URL` — base URL only, no trailing slash (e.g. `https://mlb-api.fly.dev`)
   - `ADMIN_API_KEY` — same random string as the server’s `ADMIN_API_KEY` env (omit only if the server does not enforce the key)

   From the repo root, after you know your public API URL (GitHub CLI logged in):

   ```bash
   ./scripts/set_github_actions_secrets.sh https://your-api.example.com
   ```

   Pass your existing key as a second argument if you already set `ADMIN_API_KEY` and do not want to rotate it:

   ```bash
   ./scripts/set_github_actions_secrets.sh https://your-api.example.com "$ADMIN_API_KEY"
   ```

2. Enable Actions; workflows also support **Run workflow** manually.

### systemd (Linux VPS)

Example units are under `deploy/systemd/`. Copy to `/etc/systemd/system/`, fix `WorkingDirectory` and `Environment`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mlb-refresh-actuals.timer mlb-refit-model.timer
```

### Cron (single host)

```bash
# Daily — refresh scores (add -H "X-Admin-Key: $KEY" if using ADMIN_API_KEY)
0 6 * * * API_BASE_URL=http://127.0.0.1:8000 /path/to/mlb/scripts/call_admin.sh refresh

# Weekly Monday — refit
0 5 * * 1 API_BASE_URL=http://127.0.0.1:8000 /path/to/mlb/scripts/call_admin.sh refit
```

The daily job clears in-memory caches so the next dashboard request sees
updated finals while keeping the existing posterior. The weekly refit writes
a new snapshot under `.cache/posteriors/`.

## Current status

- backend API, PyMC model, pitcher and game-level features
- posterior snapshot persistence and evaluation pipeline
- React + D3 dashboard
- admin endpoints, GitHub Actions schedules, optional `ADMIN_API_KEY`

## Legacy: Statcast analysis

The repo root may still contain an older **Statcast** tree (`etl/`, `api/`, `web/`) from the initial commit. That stack is separate from MLB Forecast V2. If you use it, install `requirements-statcast.txt` in a dedicated venv and follow that project’s `.env.example` / ETL flow.
