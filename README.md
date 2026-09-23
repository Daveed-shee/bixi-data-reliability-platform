# BIXI Data Reliability Platform

An asynchronous data platform that collects BIXI Montreal's public real-time GBFS station feed, validates its quality, and records pipeline incidents.

## Why BIXI?

BIXI publishes both historical trip data and a live station-status feed. This provides a practical, local domain for batch and near-real-time data engineering. The feed also has clear data contracts: station IDs should be unique, counts cannot be negative, and records must be fresh.

## Phase 1 architecture

```text
BIXI GBFS -> FastAPI /ingest -> Redis queue -> RQ worker -> PostgreSQL
                                                |             |
                                                +-> validations +-> incidents
```

- **FastAPI** creates ingestion jobs and serves pipeline-health endpoints.
- **Redis/RQ** keeps slow collection work out of API requests, with retry support.
- **PostgreSQL** is the source of truth for ingestion runs, snapshots, validation results, and incidents.
- **Validation rules** check required fields, duplicate station IDs, non-negative inventory, station capacity, feed freshness, and coverage of known stations.

## Run locally

Install Docker Desktop, then run:

```bash
docker compose up --build
```

Create a collection run:

```bash
curl -X POST http://localhost:8000/ingest
```

Inspect the API:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/runs
curl http://localhost:8000/incidents
curl http://localhost:8000/stations
```

Run validation unit tests without Docker:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

## Roadmap

1. Add scheduled collection and a dashboard.
2. Backfill historical BIXI trips with PySpark into bronze, silver, and gold tables.
3. Add station-demand anomaly detection and evidence-grounded incident explanations.
4. Deploy a public demo on a no-card free tier; use BigQuery Sandbox for optional cloud analytics.
