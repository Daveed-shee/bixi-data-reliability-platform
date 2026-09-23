from datetime import datetime, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Incident, IngestionRun, StationSnapshot, ValidationResult
from app import tasks


def test_repeated_feed_does_not_duplicate_snapshots_and_resolves_incident(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'bixi-test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    timestamp = int(datetime.now(timezone.utc).timestamp())
    station = {"station_id": "1", "num_bikes_available": 4, "num_docks_available": 6, "is_installed": 1, "is_renting": 1}
    status = {"last_updated": timestamp, "data": {"stations": [station]}}
    information = {"data": {"stations": [{"station_id": "1", "name": "Test", "lat": 45.5, "lon": -73.6, "capacity": 10}]}}
    monkeypatch.setattr(tasks, "get_bixi_feeds", lambda: (status, information))

    with session_factory() as session:
        session.add(IngestionRun(id=1, source_url="test"))
        session.add(IngestionRun(id=2, source_url="test"))
        session.commit()

    tasks.collect_and_validate(1)
    tasks.collect_and_validate(2)
    with session_factory() as session:
        assert session.get(IngestionRun, 1).status == "completed"
        assert session.get(IngestionRun, 2).status == "skipped"
        assert session.scalar(select(func.count()).select_from(StationSnapshot)) == 1
        assert session.scalar(select(func.count()).select_from(ValidationResult)) == 16
        assert session.scalar(select(func.count()).select_from(Incident)) == 0

    status["data"]["stations"] = [{**station, "num_bikes_available": -1}]
    with session_factory() as session:
        session.add(IngestionRun(id=3, source_url="test"))
        session.commit()
    tasks.collect_and_validate(3)
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Incident).where(Incident.status == "open")) == 1

    status["data"]["stations"] = [station]
    with session_factory() as session:
        session.add(IngestionRun(id=4, source_url="test"))
        session.commit()
    tasks.collect_and_validate(4)
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Incident).where(Incident.status == "open")) == 0
