# Blue Jays — post-game tracker

A small, descriptive view of the Toronto Blue Jays' season. Two pages:

- **Today** — the most recent completed game: win-expectancy trajectory, top
  5 leverage plays, top + negative contributors, full pitching line.
- **Season players** — every Blue Jays player ranked by net WPA across every
  completed game so far, with each player's best and worst single-game
  contribution.

No projections, no playoff odds. Just *what happened, why it mattered, and
who drove it.*

Live at **[knadella.github.io/blue-jays](https://knadella.github.io/blue-jays/)**.

## Architecture

```text
data/win_expectancy/we_table.json         empirical WE built from 4 seasons of Statcast
        ↑ scripts/pull_statcast_seasons.py   (one-shot; pulls 2021–2024 via pybaseball)
        ↑ scripts/build_we_table.py          (one-shot; aggregates per-state win prob)

backend/app/services/wpa.py               per-play WPA from MLB StatsAPI play-by-play
backend/app/services/game_story.py        builds the Today payload
backend/app/services/player_season.py     per-game cache + season aggregator

backend/app/main.py
  GET /api/health
  GET /api/today                          most recent completed Blue Jays game
  GET /api/players?season=YYYY            season-long net WPA per player

frontend/src/App.tsx                      mobile-first vertical card stack
                                          bottom tab bar: Today / Season players
```

WPA is the change in win expectancy a play produced, signed for the batting
team. The WE table is empirical: P(home wins | inning, half, outs,
base-state, score-diff), aggregated from ~731K plate appearances across
2021–2024 regular seasons. Cells with low support are smoothed via
empirical Bayes against a score-diff-pooled prior; cells with n ≥ 60 are
trusted verbatim. The final play of each game is anchored to the actual
outcome.

## Local development

```bash
# Backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
SKIP_DASHBOARD_WARMUP=1 STATCAST_REQUIRE_LOCAL=1 \
  uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Frontend defaults to same-origin in dev so Vite proxies `/api` → FastAPI.
Open <http://127.0.0.1:5173>.

Tests: `.venv/bin/python -m pytest tests/`.

## Rebuilding the WE table

The committed `data/win_expectancy/we_table.json` is built from 2021–2024.
To rebuild (e.g. add a new season):

```bash
.venv/bin/python scripts/pull_statcast_seasons.py 2025
.venv/bin/python scripts/build_we_table.py --years 2021 2022 2023 2024 2025
```

Pulls cache to `.cache/statcast_seasons/<year>.parquet` (~100 MB/season; do
not commit). Final table is ~530 KB.

## Deploy

### Backend on Fly.io

`fly.toml` configures one always-on machine in `iad` with a 3 GB persistent
volume mounted at `/data`. The Dockerfile bakes the WE table into the image
so the API works on a cold container; per-game WPA caches live on `/data`
and survive deploys.

```bash
fly deploy
```

Production env (set as Fly secrets):

| Variable | Purpose |
|---|---|
| `ADMIN_API_KEY` | If set, `POST /api/admin/*` requires header `X-Admin-Key`. |
| `CORS_ORIGINS` | Comma-separated allowed browser origins (paths stripped). |
| `MLB_SEASON` | Default season for `?season=` queries. |
| `APP_CACHE_DIR` | Set to `/data` in `fly.toml` so caches persist across deploys. |

### Frontend on GitHub Pages

The workflow `.github/workflows/deploy-github-pages.yml` builds `frontend/`
on push to `main` and publishes to Pages.

Required secrets:

- `VITE_API_URL` — Fly API base, no trailing slash (e.g. `https://mlb-forecast-api.fly.dev`).

### Scheduled jobs (GitHub Actions)

| Workflow | Schedule (UTC) | What it does |
|---|---|---|
| `schedule-refresh-statcast.yml` | `30 10 * * *` | Pulls incremental Savant Statcast for the day; warms the weekly cache. |
| `schedule-prewarm.yml` | `0 12 * * *` | Hits `/api/today` and `/api/players?season=<current-year>` so the morning's first user load is sub-second. |

Both require secret `API_BASE_URL`. The Statcast refresh additionally uses
`ADMIN_API_KEY` if the API enforces it.

## What lives where on disk

```text
data/win_expectancy/we_table.json         committed; baked into Fly image
data/statcast_local/{YYYY}_TOR.parquet    optional local Statcast extracts
.cache/statcast_seasons/{YYYY}.parquet    one-shot pulls for WE rebuild (gitignored)
.cache/game_wpa/{game_pk}.json            per-game WPA tallies (Fly: /data/game_wpa)
.cache/weekly_cache/{YYYY}_TOR.json       Statcast weekly summary cache
```

## Notes

- The WE smoothing is intentionally weak (trust threshold n ≥ 60, shrink
  toward a score-diff-pooled prior below). High-leverage cells are accurate
  to within ~0.05 of canonical WE values; B9-home-leading cells are missing
  because games end when the home team takes/keeps a lead in the bottom of
  the ninth — the final-play-anchor logic in `wpa.py` handles this.
- `data_source/savant_csv.py` and `data_source/statcast_weekly.py` are
  retained for the future Statcast/per-player drill-down. They power the
  daily refresh workflow today.
