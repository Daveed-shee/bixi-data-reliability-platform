from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


REQUIRED_FIELDS = {"station_id", "num_bikes_available", "num_docks_available"}


@dataclass(frozen=True)
class RuleResult:
    rule_name: str
    passed: bool
    details: dict[str, Any]
    severity: str = "warning"


def _inventory(station: dict[str, Any], field: str) -> int | None:
    value = station.get(field)
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if str(value) == str(number) else None


def validate_station_status(
    stations: list[dict[str, Any]],
    last_updated: int | None,
    expected_station_ids: set[str],
    max_feed_age_minutes: int,
    capacities: dict[str, int] | None = None,
    previous_schema: set[str] | None = None,
    now: datetime | None = None,
) -> list[RuleResult]:
    """Return check results without letting malformed source data crash ingestion."""
    now = now or datetime.now(timezone.utc)
    capacities = capacities or {}
    ids = [str(item.get("station_id", "")) for item in stations]
    counts = Counter(ids)
    duplicates = sorted(station_id for station_id, count in counts.items() if station_id and count > 1)
    missing_fields = [
        {"station_id": item.get("station_id"), "fields": sorted(REQUIRED_FIELDS - item.keys())}
        for item in stations
        if not REQUIRED_FIELDS.issubset(item) or not item.get("station_id")
    ]
    invalid_inventory = []
    over_capacity = []
    for item in stations:
        station_id = str(item.get("station_id", ""))
        bikes = _inventory(item, "num_bikes_available")
        docks = _inventory(item, "num_docks_available")
        if bikes is None or docks is None or bikes < 0 or docks < 0:
            invalid_inventory.append(station_id)
        elif station_id in capacities and bikes + docks > capacities[station_id]:
            over_capacity.append(station_id)

    observed_ids = set(ids) - {""}
    missing_stations = sorted(expected_station_ids - observed_ids)
    current_schema = set(stations[0]) if stations else set()
    schema_change = previous_schema is not None and current_schema != previous_schema
    try:
        age_minutes = (now - datetime.fromtimestamp(last_updated, tz=timezone.utc)).total_seconds() / 60 if last_updated else None
    except (TypeError, ValueError, OverflowError):
        age_minutes = None

    return [
        RuleResult("non_empty_feed", bool(stations), {"station_count": len(stations)}, "critical"),
        RuleResult("schema_required_fields", not missing_fields, {"affected": missing_fields[:20], "count": len(missing_fields)}),
        RuleResult(
            "schema_drift",
            not schema_change,
            {"added_fields": sorted(current_schema - (previous_schema or set())), "removed_fields": sorted((previous_schema or set()) - current_schema)} if schema_change else {},
        ),
        RuleResult("no_duplicate_station_ids", not duplicates, {"station_ids": duplicates[:20], "count": len(duplicates)}),
        RuleResult("non_negative_inventory", not invalid_inventory, {"station_ids": invalid_inventory[:20], "count": len(invalid_inventory)}),
        RuleResult("inventory_within_capacity", not over_capacity, {"station_ids": over_capacity[:20], "count": len(over_capacity)}),
        RuleResult(
            "feed_freshness",
            age_minutes is not None and 0 <= age_minutes <= max_feed_age_minutes,
            {"age_minutes": round(age_minutes, 2) if age_minutes is not None else None, "max_age_minutes": max_feed_age_minutes},
            "critical",
        ),
        RuleResult("station_coverage", not missing_stations, {"station_ids": missing_stations[:20], "count": len(missing_stations)}),
    ]
