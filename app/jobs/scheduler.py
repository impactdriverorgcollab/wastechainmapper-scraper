"""
APScheduler configuration.
All jobs write to the scrape_jobs table so you can monitor them via the DB.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

log = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="Africa/Lagos")


def start_scheduler():
    from app.jobs.runner import run_news_scrape_job

    # Run news scrape twice a day: 07:00 and 19:00 WAT
    scheduler.add_job(
        run_news_scrape_job,
        trigger=CronTrigger(hour="7,19", minute=0),
        id="news_scrape",
        replace_existing=True,
        misfire_grace_time=600,
    )

    scheduler.start()
    log.info("Scheduler started — news scrape at 07:00 and 19:00 WAT")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
