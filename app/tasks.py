from datetime import datetime, timezone

from redis import Redis
from rq import Queue, Retry
from sqlalchemy import desc, select

from app.bixi_client import get_bixi_feeds
from app.config import settings
from app.db import SessionLocal
from app.models import Incident, IngestionRun, Station, StationSnapshot, ValidationResult
from app.validation import _inventory, validate_station_status


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
            previous_raw = session.scalar(select(StationSnapshot.raw_payload).order_by(desc(StationSnapshot.id)).limit(1))
            results = validate_station_status(
                stations,
                last_updated,
                set(station_metadata),
                settings.max_feed_age_minutes,
                capacities,
                set(previous_raw) if previous_raw else None,
            )

            for result in results:
                session.add(ValidationResult(ingestion_run_id=run.id, rule_name=result.rule_name, passed=result.passed, details=result.details))
                active = session.scalar(select(Incident).where(Incident.rule_name == result.rule_name, Incident.status == "open").limit(1))
                if not result.passed:
                    if active:
                        active.ingestion_run_id = run.id
                        active.evidence = result.details
                    else:
                        session.add(Incident(
                            ingestion_run_id=run.id,
                            rule_name=result.rule_name,
                            severity=result.severity,
                            summary=f"{result.rule_name} failed during BIXI collection run {run.id}",
                            evidence=result.details,
                        ))
                elif active:
                    active.status = "resolved"

            observed_at = datetime.fromtimestamp(last_updated, tz=timezone.utc) if last_updated else datetime.now(timezone.utc)
            already_stored = session.scalar(
                select(StationSnapshot.id).where(StationSnapshot.observed_at == observed_at).limit(1)
            ) is not None
            seen_ids: set[str] = set()
            for raw_station in stations if not already_stored else []:
                station_id = str(raw_station.get("station_id", ""))
                bikes = _inventory(raw_station, "num_bikes_available")
                docks = _inventory(raw_station, "num_docks_available")
                if not station_id or station_id in seen_ids or bikes is None or docks is None or bikes < 0 or docks < 0:
                    continue
                seen_ids.add(station_id)
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
                    bikes_available=bikes,
                    docks_available=docks,
                    is_installed=bool(raw_station.get("is_installed", 0)),
                    is_renting=bool(raw_station.get("is_renting", 0)),
                    raw_payload=raw_station,
                ))

            run.records_received = len(stations)
            run.status = "skipped" if already_stored else "completed"
            run.completed_at = datetime.now(timezone.utc)
            session.commit()
        except Exception as exc:
            session.rollback()
            run = session.get(IngestionRun, run_id)
            run.status = "failed"
            run.error_message = str(exc)
            run.completed_at = datetime.now(timezone.utc)
            session.commit()
            raise
