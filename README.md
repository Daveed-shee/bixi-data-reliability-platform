# BIXI Data Reliability Platform

A local data engineering and backend project that monitors BIXI Montréal's public GBFS station feed. It collects station status and metadata, checks data quality, keeps a history of snapshots and validation runs, and shows pipeline health in a small dashboard.

## Why BIXI?

BIXI publishes a live station feed and historical trip files. This gives the project a real, Montréal-based source for recurring ingestion now and a batch backfill later. Station IDs, feed timestamps, inventory counts, and capacity provide concrete rules that can be tested and monitored.

## Phase 1 architecture

```text
Scheduler (every 5 min) -> FastAPI /ingest -> Redis/RQ queue -> worker
                                                         |
                                             BIXI GBFS status + information
                                                         |
                                              checks + incident lifecycle
                                                         |
                                          PostgreSQL runs, stations, snapshots
                                                         |
                                             FastAPI + live dashboard
```

Redis holds pending work and retries; PostgreSQL holds the durable records. The scheduler retries startup failures every 15 seconds. A run with an already stored BIXI source timestamp is marked `skipped`, so polling the same feed does not duplicate station snapshots. Failed checks create one open incident per rule; a later passing check resolves it.

The worker checks nonempty feeds, required fields, schema drift, duplicate station IDs, inventory types and nonnegative counts, inventory against capacity, timestamp freshness, and station coverage against the current information feed. Malformed records are reported and excluded from snapshots without crashing the full run.

## Run locally

Install and start Docker Desktop, then from this folder:

```bash
docker compose up --build -d
```

Open [the dashboard](http://localhost:8000/dashboard) or [the API documentation](http://localhost:8000/docs). The scheduler submits its first run after startup and continues every five minutes. You can also start a run manually:

```bash
curl -X POST http://localhost:8000/ingest
```

Useful endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Latest run, source timestamp, and open incident count |
| `GET /runs` and `GET /runs/{id}` | Run history and each run's validation results |
| `GET /incidents` and `GET /incidents/{id}` | Incident list and evidence; filter with `?status_filter=open` |
| `GET /stations` | One current row per station from the newest completed snapshot |
| `POST /ingest` | Queue a manual collection run |

Use `docker compose logs -f scheduler worker` to watch collection. `docker compose down` stops the stack while preserving PostgreSQL data in a named Docker volume.

## Tests and local commits

Without Docker:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

Tests cover validation edge cases, repeated feed timestamps, incident recovery, and current API responses. GitHub Actions runs tests and builds the Docker image on pushes and pull requests once the repository is published.

## Scope and next steps

Phase 1 is a local MVP. A single worker processes jobs serially; scaling to multiple workers would need a database uniqueness constraint and migration for source timestamps. The dashboard uses a station table, which keeps the first version easy to run and inspect.

Next phases: historical BIXI trip processing with PySpark, demand anomaly detection, evidence-grounded incident explanations, and a public demo on a no-card hosting option. BigQuery Sandbox can be used separately for cloud analytics without a billing account.
