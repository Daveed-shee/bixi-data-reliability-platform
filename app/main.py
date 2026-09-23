from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, engine, get_session
from app.models import Incident, IngestionRun, Station, StationSnapshot, ValidationResult
from app.tasks import enqueue_ingestion


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="BIXI Data Reliability Platform", version="0.1.0", lifespan=lifespan)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/dashboard")


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(Path(__file__).parent / "static" / "dashboard.html")


@app.get("/health")
def health(session: Session = Depends(get_session)):
    latest_run = session.scalar(select(IngestionRun).order_by(desc(IngestionRun.created_at)).limit(1))
    latest_snapshot = session.scalar(select(StationSnapshot.observed_at).order_by(desc(StationSnapshot.observed_at)).limit(1))
    open_incidents = session.scalar(select(func.count()).select_from(Incident).where(Incident.status == "open"))
    return {
        "status": "ok",
        "latest_run_status": latest_run.status if latest_run else None,
        "latest_snapshot_at": latest_snapshot,
        "open_incidents": open_incidents,
    }


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
    runs = session.scalars(select(IngestionRun).order_by(desc(IngestionRun.id)).limit(50)).all()
    return [{"id": run.id, "status": run.status, "records_received": run.records_received, "created_at": run.created_at, "completed_at": run.completed_at, "error_message": run.error_message} for run in runs]


@app.get("/runs/{run_id}")
def get_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(IngestionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    results = session.scalars(select(ValidationResult).where(ValidationResult.ingestion_run_id == run_id).order_by(ValidationResult.id)).all()
    return {
        "id": run.id, "status": run.status, "records_received": run.records_received,
        "created_at": run.created_at, "started_at": run.started_at, "completed_at": run.completed_at,
        "error_message": run.error_message,
        "validations": [{"rule_name": item.rule_name, "passed": item.passed, "details": item.details} for item in results],
    }


@app.get("/incidents")
def list_incidents(status_filter: Literal["all", "open", "resolved"] = "all", session: Session = Depends(get_session)):
    query = select(Incident)
    if status_filter != "all":
        query = query.where(Incident.status == status_filter)
    incidents = session.scalars(query.order_by(desc(Incident.id)).limit(100)).all()
    return [{"id": incident.id, "ingestion_run_id": incident.ingestion_run_id, "rule_name": incident.rule_name, "severity": incident.severity, "summary": incident.summary, "status": incident.status, "evidence": incident.evidence, "created_at": incident.created_at} for incident in incidents]


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: int, session: Session = Depends(get_session)):
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {
        "id": incident.id, "ingestion_run_id": incident.ingestion_run_id,
        "rule_name": incident.rule_name, "severity": incident.severity,
        "summary": incident.summary, "evidence": incident.evidence,
        "status": incident.status, "created_at": incident.created_at,
    }


@app.get("/stations")
def list_stations(limit: int = Query(default=2000, ge=1, le=3000), session: Session = Depends(get_session)):
    latest_run_id = session.scalar(select(IngestionRun.id).where(IngestionRun.status == "completed").order_by(desc(IngestionRun.id)).limit(1))
    if latest_run_id is None:
        return []
    rows = session.execute(
        select(StationSnapshot, Station)
        .join(Station, Station.station_id == StationSnapshot.station_id)
        .where(StationSnapshot.ingestion_run_id == latest_run_id)
        .order_by(StationSnapshot.station_id)
        .limit(limit)
    ).all()
    return [{
        "station_id": snapshot.station_id, "name": station.name,
        "latitude": station.latitude, "longitude": station.longitude,
        "capacity": station.capacity, "bikes_available": snapshot.bikes_available,
        "docks_available": snapshot.docks_available, "is_installed": snapshot.is_installed,
        "is_renting": snapshot.is_renting, "observed_at": snapshot.observed_at,
    } for snapshot, station in rows]
