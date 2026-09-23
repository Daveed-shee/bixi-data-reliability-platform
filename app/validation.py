from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class RuleResult:
    rule_name: str
    passed: bool
    details: dict[str, Any]
    severity: str = "warning"


def validate_station_status(
    stations: list[dict[str, Any]],
    last_updated: int | None,
    known_station_ids: set[str],
    max_feed_age_minutes: int,
    capacities: dict[str, int] | None = None,
    now: datetime | None = None,
) -> list[RuleResult]:
    now = now or datetime.now(timezone.utc)
    station_ids = [str(station.get("station_id", "")) for station in stations]
    duplicates = sorted({station_id for station_id in station_ids if station_ids.count(station_id) > 1})
    invalid_counts = [
        station.get("station_id")
        for station in stations
        if int(station.get("num_bikes_available", 0)) < 0 or int(station.get("num_docks_available", 0)) < 0
    ]
    missing_required = [
        station.get("station_id", "unknown")
        for station in stations
        if not station.get("station_id") or "num_bikes_available" not in station or "num_docks_available" not in station
    ]
    current_station_ids = set(station_ids)
    missing_known = sorted(known_station_ids - current_station_ids)
    capacities = capacities or {}
    over_capacity = [
        station.get("station_id")
        for station in stations
        if str(station.get("station_id")) in capacities
        and int(station.get("num_bikes_available", 0)) + int(station.get("num_docks_available", 0))
        > capacities[str(station.get("station_id"))]
    ]
    age_minutes = None
    if last_updated:
        age_minutes = max(0, (now - datetime.fromtimestamp(last_updated, tz=timezone.utc)).total_seconds() / 60)

    return [
        RuleResult("schema_required_fields", not missing_required, {"invalid_station_ids": missing_required}),
        RuleResult("no_duplicate_station_ids", not duplicates, {"duplicate_station_ids": duplicates}),
        RuleResult("non_negative_inventory", not invalid_counts, {"invalid_station_ids": invalid_counts}),
        RuleResult("inventory_within_capacity", not over_capacity, {"invalid_station_ids": over_capacity}),
        RuleResult(
            "feed_freshness",
            age_minutes is not None and age_minutes <= max_feed_age_minutes,
            {"age_minutes": round(age_minutes, 2) if age_minutes is not None else None, "max_age_minutes": max_feed_age_minutes},
            "critical",
        ),
        RuleResult("known_station_coverage", not missing_known, {"missing_station_ids": missing_known}),
    ]
