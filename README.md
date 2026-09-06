# wastewatch-scraper

Automated news intelligence pipeline for WasteWatch. Runs on a GitHub Actions schedule — no server required.

Scrapes Nigerian news RSS feeds twice daily, uses Claude AI to classify articles and extract structured incident data, geocodes location mentions against a local Rivers State gazetteer, and writes verified reports to the shared PostgreSQL database.

## How it works

```
RSS feeds (Google News, Vanguard, Punch)
  → keyword filter
  → Claude Haiku: is this real dumping? where? what kind of waste?
  → geocoder: community name → lat/lng (gazetteer → Nominatim fallback)
  → INSERT into reports / waste_flows
```

The job runs at **07:00 and 19:00 WAT** via two GitHub Actions cron triggers. It can also be triggered manually from the Actions tab once the workflow file is on your default branch.

## Why Claude AI

Raw keyword matching is not enough for Nigerian news. The same word — "dump" — appears in political articles, press conferences, and music reviews. Claude Haiku solves three things keyword matching cannot:

1. **Relevance classification** — distinguishes articles about actual illegal dumping from noise (political "dumping" of candidates, "dump" as slang, etc.)
2. **Structured extraction** — pulls out location name, waste type, severity, urgency, and estimated tonnage from free-form prose in a single API call, without needing a custom-trained model
3. **Collection event detection** — tells apart a new dump site (write a `report`) from a government clean-up operation (write a `waste_flow`), which are grammatically similar sentences

The alternative would be a custom fine-tuned NER model, which requires labelled training data we don't have yet. At the current scrape volume (~30 articles per run), Haiku costs roughly $0.002 per run — negligible.

## Setup

**1. Clone and install**
```bash
git clone https://github.com/your-org/wastewatch-scraper
cd wastewatch-scraper
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

**2. Environment**
```bash
cp .env.example .env
# Fill in DATABASE_URL and ANTHROPIC_API_KEY
```

**3. GitHub Actions (production)**

Add these repository secrets (`Settings → Secrets and variables → Actions`):

| Secret | Description |
|--------|-------------|
| `DATABASE_URL` | PostgreSQL connection string (`postgresql://user:pass@host/db`) |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `WHATSAPP_VERIFY_TOKEN` | WhatsApp webhook verify token |
| `WHATSAPP_ACCESS_TOKEN` | WhatsApp Cloud API access token |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp phone number ID |

> The "Run workflow" button appears in the Actions tab only after this file is pushed to your default branch (main).

**4. Run locally (one-off)**
```bash
python run_once.py
```

## Project structure

```
app/
  config.py          # Pydantic settings (reads .env)
  database.py        # SQLAlchemy engine + SessionLocal
  scrapers/
    news.py          # RSS scrapers: Google News, Vanguard, Punch
  nlp/
    extractor.py     # Claude Haiku extraction + classification
  geocoding/
    resolver.py      # Gazetteer exact → fuzzy → Nominatim
  jobs/
    runner.py        # End-to-end job: scrape → NLP → geocode → DB
    scheduler.py     # APScheduler config (used in server mode)
  routers/
    jobs.py          # POST /jobs/news-scrape (manual trigger via HTTP)
  webhooks/
    whatsapp.py      # WhatsApp Cloud API webhook
main.py              # FastAPI app (optional server mode)
worker.py            # Long-running worker (used if deploying as a service)
run_once.py          # One-shot entry point for GitHub Actions
.github/
  workflows/
    scrape.yml       # Cron: 06:00 + 18:00 UTC daily
```

## Local development with the API

The scraper writes directly to the same Postgres database as `wastewatch-api`. Run the API first to apply migrations, then run the scraper against the same `DATABASE_URL`.
