"""
Job runner — processes a single scrape job end-to-end:
  1. Claim a PENDING ScrapeJob row
  2. Run the scraper
  3. Run NLP extraction on each article
  4. Geocode extracted locations
  5. Write Report rows to Postgres
  6. Mark job DONE or FAILED
"""

import logging
import json
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import SessionLocal
from app.scrapers.news import run_all_news_scrapers, ScrapedArticle
from app.nlp.extractor import extract_from_text, waste_type_to_enum
from app.geocoding.resolver import resolve_location

log = logging.getLogger(__name__)


def _compute_confidence(nlp_confidence: float, geocode_source: str) -> float:
    source_weight = {"gazetteer_exact": 1.0, "gazetteer_fuzzy": 0.85, "nominatim": 0.7}
    return round(nlp_confidence * source_weight.get(geocode_source, 0.5), 3)


def run_news_scrape_job(job_id: str | None = None) -> dict:
    db: Session = SessionLocal()
    created_count = 0
    skipped_count = 0

    try:
        # Claim or create the job row
        if job_id is None:
            result = db.execute(text("""
                INSERT INTO scrape_jobs (id, job_type, status, started_at, created_at)
                VALUES (gen_random_uuid(), 'news_scrape', 'RUNNING', NOW(), NOW())
                RETURNING id
            """))
            db.commit()
            job_id = str(result.fetchone()[0])
        else:
            db.execute(text("""
                UPDATE scrape_jobs SET status = 'RUNNING', started_at = NOW()
                WHERE id = CAST(:id AS uuid)
            """), {"id": job_id})
            db.commit()

        articles: list[ScrapedArticle] = run_all_news_scrapers()

        for article in articles:
            exists = db.execute(text(
                "SELECT 1 FROM reports WHERE source_url = :url LIMIT 1"
            ), {"url": article.url}).fetchone()
            if exists:
                skipped_count += 1
                continue

            text_to_extract = f"{article.title}\n\n{article.full_text}"
            extraction = extract_from_text(text_to_extract)

            if not extraction["is_dumping_related"]:
                skipped_count += 1
                continue

            primary_location = extraction.get("primary_location")
            geo = None
            geocode_status = "UNRESOLVED"
            geocode_source = None

            if primary_location:
                geo = resolve_location(primary_location, db)
                if geo:
                    geocode_status = {
                        "gazetteer_exact": "RESOLVED_GAZETTEER",
                        "gazetteer_fuzzy": "RESOLVED_GAZETTEER",
                        "nominatim": "RESOLVED_NOMINATIM",
                    }.get(geo.source, "UNRESOLVED")
                    geocode_source = geo.source

            confidence = _compute_confidence(
                extraction.get("confidence", 0.3),
                geocode_source or "",
            ) if geo else round(extraction.get("confidence", 0.3) * 0.5, 3)

            waste_type = waste_type_to_enum(extraction.get("waste_type", "unknown"))

            # If the article describes a collection event, create a WasteFlow record
            is_collection = extraction.get("is_collection_event", False)
            if is_collection and geo:
                try:
                    db.execute(text("""
                        INSERT INTO waste_flows (
                            id, waste_type, status,
                            origin_lat, origin_lng,
                            lga, ward,
                            estimated_tonnage,
                            collected_at, notes,
                            created_at, updated_at
                        ) VALUES (
                            gen_random_uuid(),
                            CAST(:waste_type AS "WasteType"),
                            CAST('COLLECTED' AS "FlowStatus"),
                            :lat, :lng,
                            :lga, :ward,
                            :tonnage,
                            NOW(), :notes,
                            NOW(), NOW()
                        )
                    """), {
                        "waste_type": waste_type,
                        "lat": geo.latitude,
                        "lng": geo.longitude,
                        "lga": geo.lga if hasattr(geo, 'lga') else None,
                        "ward": geo.ward if hasattr(geo, 'ward') else None,
                        "tonnage": extraction.get("estimated_tonnage"),
                        "notes": f"Auto-detected from article: {article.url}",
                    })
                    db.commit()
                    log.info("Created WasteFlow record from collection event at %s", primary_location)
                except Exception as flow_exc:
                    log.warning("Failed to create WasteFlow: %s", flow_exc)
                    db.rollback()

            db.execute(text("""
                INSERT INTO reports (
                    id, raw_text, source_url, source_type,
                    extracted_location_text, extracted_waste_type,
                    extracted_severity, extracted_urgency,
                    geocode_status, geocoded_latitude, geocoded_longitude, geocode_source,
                    confidence_score, verification_status,
                    scraped_at, created_at, updated_at
                ) VALUES (
                    gen_random_uuid(),
                    :raw_text, :source_url, 'NEWS_SCRAPE',
                    :location_text, CAST(:waste_type AS "WasteType"),
                    :severity, :urgency,
                    CAST(:geocode_status AS "GeocodeStatus"),
                    :lat, :lng, :geocode_source,
                    :confidence, 'UNVERIFIED',
                    NOW(), NOW(), NOW()
                )
            """), {
                "raw_text": text_to_extract[:10000],
                "source_url": article.url,
                "location_text": primary_location,
                "waste_type": waste_type,
                "severity": extraction.get("severity", "unknown"),
                "urgency": extraction.get("urgency", "unknown"),
                "geocode_status": geocode_status,
                "lat": geo.latitude if geo else None,
                "lng": geo.longitude if geo else None,
                "geocode_source": geocode_source,
                "confidence": confidence,
            })
            db.commit()
            created_count += 1

        db.execute(text("""
            UPDATE scrape_jobs
            SET status = 'DONE', completed_at = NOW(),
                metadata = CAST(:meta AS jsonb)
            WHERE id = CAST(:id AS uuid)
        """), {
            "id": job_id,
            "meta": json.dumps({"created": created_count, "skipped": skipped_count}),
        })
        db.commit()
        log.info("Job %s done: %d created, %d skipped", job_id, created_count, skipped_count)
        return {"job_id": job_id, "created": created_count, "skipped": skipped_count}

    except Exception as exc:
        log.error("Job %s failed: %s", job_id, exc, exc_info=True)
        try:
            db.execute(text("""
                UPDATE scrape_jobs
                SET status = 'FAILED', completed_at = NOW(), error_msg = :err
                WHERE id = CAST(:id AS uuid)
            """), {"id": job_id, "err": str(exc)[:2000]})
            db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()
