"""Manual job trigger endpoints — useful for testing and one-off runs."""

from fastapi import APIRouter, BackgroundTasks
from app.jobs.runner import run_news_scrape_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/news-scrape")
async def trigger_news_scrape(background_tasks: BackgroundTasks):
    """Trigger an immediate news scrape run (runs in background)."""
    background_tasks.add_task(run_news_scrape_job)
    return {"status": "queued", "message": "News scrape job started in background"}
