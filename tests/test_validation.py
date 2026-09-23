from datetime import datetime, timezone

from app.validation import validate_station_status


NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def test_validation_flags_duplicates_negative_counts_and_stale_feed():
    stations = [
        {"station_id": "1", "num_bikes_available": 2, "num_docks_available": 8},
        {"station_id": "1", "num_bikes_available": -1, "num_docks_available": 7},
    ]
    results = validate_station_status(
        stations,
        int(datetime(2026, 9, 21, 11, 40, tzinfo=timezone.utc).timestamp()),
        known_station_ids={"1", "2"},
        max_feed_age_minutes=15,
        capacities={"1": 8},
        now=NOW,
    )
    by_name = {result.rule_name: result for result in results}
    assert not by_name["no_duplicate_station_ids"].passed
    assert not by_name["non_negative_inventory"].passed
    assert not by_name["inventory_within_capacity"].passed
    assert not by_name["feed_freshness"].passed
    assert not by_name["known_station_coverage"].passed


def test_validation_passes_healthy_feed():
    stations = [{"station_id": "1", "num_bikes_available": 2, "num_docks_available": 8}]
    results = validate_station_status(
        stations,
        int(NOW.timestamp()),
        known_station_ids={"1"},
        max_feed_age_minutes=15,
        capacities={"1": 10},
        now=NOW,
    )
    assert all(result.passed for result in results)
