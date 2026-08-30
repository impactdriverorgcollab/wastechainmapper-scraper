import logging
import uvicorn
from fastapi import FastAPI
from app.config import settings
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.routers.jobs import router as jobs_router
from app.webhooks.whatsapp import router as whatsapp_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

app = FastAPI(
    title="WasteWatch Scraper",
    description="News scraping, NLP extraction, and geocoding for illegal dump site detection",
    version="0.1.0",
)

app.include_router(jobs_router)
app.include_router(whatsapp_router)


@app.on_event("startup")
async def startup():
    start_scheduler()


@app.on_event("shutdown")
async def shutdown():
    stop_scheduler()


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=True)
