from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, engine, get_session
from app.models import Incident, IngestionRun, Station, StationSnapshot
from app.tasks import enqueue_ingestion


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="BIXI Data Reliability Platform", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health(session: Session = Depends(get_session)):
    latest_run = session.scalar(select(IngestionRun).order_by(desc(IngestionRun.created_at)).limit(1))
    return {"status": "ok", "latest_run_status": latest_run.status if latest_run else None}


@app.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
def ingest(session: Session = Depends(get_session)):
    run = IngestionRun(status="queued", source_url=settings.bixi_gbfs_url)
    session.add(run)
    session.commit()
    session.refresh(run)
    try:
        job_id = enqueue_ingestion(run.id)
    except Exception as exc:
        run.status = "failed"
        run.error_message = f"Could not enqueue job: {exc}"
        session.commit()
        raise HTTPException(status_code=503, detail="Queue is unavailable") from exc
    return {"run_id": run.id, "job_id": job_id, "status": run.status}


@app.get("/runs")
def list_runs(session: Session = Depends(get_session)):
    runs = session.scalars(select(IngestionRun).order_by(desc(IngestionRun.created_at)).limit(50)).all()
    return [{"id": run.id, "status": run.status, "records_received": run.records_received, "created_at": run.created_at} for run in runs]


@app.get("/incidents")
def list_incidents(session: Session = Depends(get_session)):
    incidents = session.scalars(select(Incident).order_by(desc(Incident.created_at)).limit(100)).all()
    return [{"id": incident.id, "rule_name": incident.rule_name, "severity": incident.severity, "summary": incident.summary, "status": incident.status, "evidence": incident.evidence} for incident in incidents]


@app.get("/stations")
def list_stations(session: Session = Depends(get_session)):
    latest_snapshots = session.scalars(select(StationSnapshot).order_by(desc(StationSnapshot.observed_at)).limit(500)).all()
    return [{"station_id": snapshot.station_id, "bikes_available": snapshot.bikes_available, "docks_available": snapshot.docks_available, "observed_at": snapshot.observed_at} for snapshot in latest_snapshots]

