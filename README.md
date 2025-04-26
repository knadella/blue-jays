# Blue Jays Statcast Analysis

A data visualization project analyzing Toronto Blue Jays' Statcast data.

## Project Structure

- `etl/`: Python pipeline for fetching and processing Statcast data
- `api/`: FastAPI server for serving the processed data
- `web/`: D3.js frontend for visualizing the data
- `.github/workflows/`: GitHub Actions for automated data updates

## Quick Start

1. Clone the repository
2. Copy `.env.example` to `.env` and fill in your configuration
3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the ETL pipeline:
   ```bash
   python etl/etl.py
   ```
5. Start the API server:
   ```bash
   uvicorn api.main:app --reload
   ```
6. Open `web/index.html` in your browser

## Deployment Notes

- The ETL pipeline runs nightly via GitHub Actions
- API can be deployed to any FastAPI-compatible hosting service
- Web frontend is static and can be hosted on any web server

## Environment Variables

- `DB_URL`: Database connection string
- `STATCAST_START`: Start date for Statcast data (YYYY-MM-DD)
- `STATCAST_END`: End date for Statcast data (YYYY-MM-DD) 