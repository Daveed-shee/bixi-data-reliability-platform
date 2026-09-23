from typing import Any

import httpx

from app.config import settings


def get_bixi_feeds() -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve BIXI's GBFS index and return status plus station metadata payloads."""
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        index = client.get(settings.bixi_gbfs_url)
        index.raise_for_status()
        feeds = index.json()["data"]["en"]["feeds"]
        status_url = next(feed["url"] for feed in feeds if feed["name"] == "station_status")
        information_url = next(feed["url"] for feed in feeds if feed["name"] == "station_information")
        status_response = client.get(status_url)
        information_response = client.get(information_url)
        status_response.raise_for_status()
        information_response.raise_for_status()
        return status_response.json(), information_response.json()
