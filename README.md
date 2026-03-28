# MLB Forecast V2

`MLB Forecast` is now being rebuilt as a split application:

- A `Python + FastAPI` backend for MLB data ingestion, Bayesian model fitting in `PyMC`, posterior storage, and season simulation.
- A `React + D3` frontend for customizable interactive visualizations and dashboard views.

The old Elo + Streamlit app has been retired from the main architecture.

## Architecture

```text
data_source/mlb_api.py
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

## Current Status

This repo now contains the first pass of the V2 rewrite:

- backend API scaffolding
- posterior snapshot persistence
- PyMC model definition and bootstrap fallback
- React + D3 dashboard shell

Still to deepen:

- richer daily posterior history
- more exact elimination-number logic
- finer D3 interactions and filtering
- production-ready caching and background refits
