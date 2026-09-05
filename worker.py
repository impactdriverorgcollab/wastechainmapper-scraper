import logging
import time
from app.jobs.scheduler import start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

if __name__ == "__main__":
    start_scheduler()
    while True:
        time.sleep(60)
