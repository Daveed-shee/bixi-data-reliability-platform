"""A small local scheduler that asks the API to enqueue a collection run."""

import logging
import os
import time

import httpx


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    interval = max(60, int(os.getenv("INGEST_INTERVAL_SECONDS", "3600")))
    api_url = os.getenv("INGEST_API_URL", "http://api:8000/ingest")
    while True:
        try:
            response = httpx.post(api_url, timeout=15)
            response.raise_for_status()
            logger.info("Scheduled BIXI ingestion: %s", response.json())
            time.sleep(interval)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Could not schedule ingestion: %s; retrying in 15 seconds", exc)
            time.sleep(15)


if __name__ == "__main__":
    main()
