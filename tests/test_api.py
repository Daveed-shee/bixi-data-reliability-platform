from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_session
from app.main import app
from app.models import Incident, IngestionRun, Station, StationSnapshot, ValidationResult


def test_api_returns_current_station_set_and_incident_details(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'api-test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    observed_at = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add_all([
            IngestionRun(id=1, source_url="test", status="completed", records_received=2),
            IngestionRun(id=2, source_url="test", status="skipped", records_received=2),
            Station(station_id="1", name="Station One", capacity=10),
            Station(station_id="2", name="Station Two", capacity=20),
        ])
        session.flush()
        for station_id in ("1", "2"):
            session.add(StationSnapshot(
                ingestion_run_id=1, station_id=station_id, observed_at=observed_at,
                bikes_available=3, docks_available=7, is_installed=True, is_renting=True,
                raw_payload={"station_id": station_id},
            ))
        session.add(ValidationResult(ingestion_run_id=1, rule_name="feed_freshness", passed=False, details={"age_minutes": 20}))
        session.add(Incident(ingestion_run_id=1, rule_name="feed_freshness", severity="critical", summary="Feed stale", evidence={"age_minutes": 20}))
        session.commit()

    def test_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    try:
        client = TestClient(app)
        stations = client.get("/stations")
        assert stations.status_code == 200
        assert len(stations.json()) == 2
        assert stations.json()[0]["name"] == "Station One"
        assert client.get("/stations?limit=0").status_code == 422
        assert client.get("/health").json()["open_incidents"] == 1
        assert client.get("/runs/1").json()["validations"][0]["rule_name"] == "feed_freshness"
        assert client.get("/incidents/1").json()["evidence"]["age_minutes"] == 20
        assert client.get("/incidents/999").status_code == 404
        assert "Station feed health" in client.get("/dashboard").text
    finally:
        app.dependency_overrides.clear()
