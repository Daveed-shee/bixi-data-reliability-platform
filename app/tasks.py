from datetime import datetime, timezone

from redis import Redis
from rq import Queue, Retry
from sqlalchemy import select

from app.bixi_client import get_bixi_feeds
from app.config import settings
from app.db import SessionLocal
from app.models import Incident, IngestionRun, Station, StationSnapshot, ValidationResult
from app.validation import validate_station_status


def get_queue() -> Queue:
    return Queue("bixi", connection=Redis.from_url(settings.redis_url))


def enqueue_ingestion(run_id: int) -> str:
    job = get_queue().enqueue("app.tasks.collect_and_validate", run_id, job_timeout=90, retry=Retry(max=2))
    return job.id


def collect_and_validate(run_id: int) -> None:
    with SessionLocal() as session:
        run = session.get(IngestionRun, run_id)
        if run is None:
            raise ValueError(f"Ingestion run {run_id} does not exist")
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        session.commit()

        try:
            status_payload, information_payload = get_bixi_feeds()
            data = status_payload["data"]
            stations = data["stations"]
            information = information_payload["data"]["stations"]
            station_metadata = {str(item["station_id"]): item for item in information}
            capacities = {
                station_id: int(item["capacity"])
                for station_id, item in station_metadata.items()
                if item.get("capacity") is not None
            }
            last_updated = status_payload.get("last_updated")
            known_ids = set(session.scalars(select(Station.station_id)).all())
            results = validate_station_status(stations, last_updated, known_ids, settings.max_feed_age_minutes, capacities)

            for result in results:
                session.add(ValidationResult(ingestion_run_id=run.id, rule_name=result.rule_name, passed=result.passed, details=result.details))
                if not result.passed:
                    session.add(Incident(
                        ingestion_run_id=run.id,
                        rule_name=result.rule_name,
                        severity=result.severity,
                        summary=f"{result.rule_name} failed during BIXI collection run {run.id}",
                        evidence=result.details,
                    ))

            observed_at = datetime.fromtimestamp(last_updated, tz=timezone.utc) if last_updated else datetime.now(timezone.utc)
            for raw_station in stations:
                station_id = str(raw_station["station_id"])
                station = session.get(Station, station_id)
                if station is None:
                    station = Station(station_id=station_id)
                    session.add(station)
                metadata = station_metadata.get(station_id, {})
                station.name = metadata.get("name")
                station.latitude = metadata.get("lat")
                station.longitude = metadata.get("lon")
                station.capacity = capacities.get(station_id)
                station.is_active = bool(raw_station.get("is_installed", 0))
                session.add(StationSnapshot(
                    ingestion_run_id=run.id,
                    station_id=station_id,
                    observed_at=observed_at,
                    bikes_available=int(raw_station.get("num_bikes_available", 0)),
                    docks_available=int(raw_station.get("num_docks_available", 0)),
                    is_installed=bool(raw_station.get("is_installed", 0)),
                    is_renting=bool(raw_station.get("is_renting", 0)),
                    raw_payload=raw_station,
                ))

            run.records_received = len(stations)
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            session.commit()
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            run.completed_at = datetime.now(timezone.utc)
            session.commit()
            raise
