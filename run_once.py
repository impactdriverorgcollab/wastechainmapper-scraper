"""
One-shot runner for GitHub Actions.
Runs the news scrape job once and exits — no server, no scheduler.
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)

from app.jobs.runner import run_news_scrape_job

if __name__ == "__main__":
    try:
        result = run_news_scrape_job()
        print(f"Done: {result}")
        sys.exit(0)
    except Exception as exc:
        logging.getLogger(__name__).error("Scrape job failed: %s", exc, exc_info=True)
        sys.exit(1)
