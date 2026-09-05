"""
WhatsApp Cloud API webhook handler.

Receives citizen reports: photo + text + optional location pin.
Writes a report row with source_type = WHATSAPP_CITIZEN.

Setup:
1. In Meta Developer Console, set webhook URL to https://your-domain/webhooks/whatsapp
2. Set the verify token to WHATSAPP_VERIFY_TOKEN in your .env
3. Subscribe to the 'messages' field

The incoming message format follows WhatsApp Cloud API v18+.
"""

import asyncio
import logging
from fastapi import APIRouter, Request, Response, HTTPException, Query
from sqlalchemy import text
from app.config import settings
from app.database import SessionLocal
from app.nlp.extractor import extract_from_text, waste_type_to_enum
from app.geocoding.resolver import resolve_location

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/whatsapp")
async def whatsapp_verify(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    """WhatsApp webhook verification handshake."""
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp")
async def whatsapp_receive(request: Request):
    """Receive incoming WhatsApp messages."""
    payload = await request.json()

    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])

                for msg in messages:
                    await _process_message(msg, value.get("contacts", []))

    except Exception as exc:
        log.error("WhatsApp webhook error: %s", exc, exc_info=True)

    # Always return 200 — WhatsApp will retry on non-200
    return {"status": "ok"}


async def _process_message(msg: dict, contacts: list):
    msg_type = msg.get("type")
    sender = contacts[0].get("profile", {}).get("name", "Unknown") if contacts else "Unknown"

    # Extract text content
    raw_text = ""
    if msg_type == "text":
        raw_text = msg.get("text", {}).get("body", "")
    elif msg_type == "image":
        caption = msg.get("image", {}).get("caption", "")
        raw_text = caption or "[image with no caption]"
    elif msg_type == "document":
        raw_text = msg.get("document", {}).get("caption", "") or "[document]"

    if not raw_text or raw_text == "[image with no caption]":
        return

    # Extract location pin if provided
    location_pin = msg.get("location")
    pin_lat = location_pin.get("latitude") if location_pin else None
    pin_lng = location_pin.get("longitude") if location_pin else None
    pin_name = location_pin.get("name") if location_pin else None

    # Run NLP extraction on the message text (offloaded to thread pool — sync HTTP call)
    extraction = await asyncio.get_event_loop().run_in_executor(
        None, extract_from_text, f"WhatsApp citizen report from {sender}: {raw_text}"
    )

    db = SessionLocal()
    try:
        # Use location pin if provided, else geocode extracted text
        geo_lat = pin_lat
        geo_lng = pin_lng
        geocode_status = "RESOLVED_GAZETTEER" if pin_lat else "UNRESOLVED"
        geocode_source = "whatsapp_pin" if pin_lat else None

        if not pin_lat and extraction.get("primary_location"):
            geo = resolve_location(extraction["primary_location"], db)
            if geo:
                geo_lat = geo.latitude
                geo_lng = geo.longitude
                geocode_status = {
                    "gazetteer_exact": "RESOLVED_GAZETTEER",
                    "gazetteer_fuzzy": "RESOLVED_GAZETTEER",
                    "nominatim": "RESOLVED_NOMINATIM",
                }.get(geo.source, "UNRESOLVED")
                geocode_source = geo.source

        waste_type = waste_type_to_enum(extraction.get("waste_type", "unknown"))
        confidence = round(extraction.get("confidence", 0.5) * 0.9, 3)  # citizen reports get slight boost

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
                :raw_text, NULL, 'WHATSAPP_CITIZEN',
                :location_text, :waste_type::\"WasteType\",
                :severity, :urgency,
                :geocode_status::\"GeocodeStatus\",
                :lat, :lng, :geocode_source,
                :confidence, 'UNVERIFIED',
                NOW(), NOW(), NOW()
            )
        """), {
            "raw_text": raw_text[:10000],
            "location_text": pin_name or extraction.get("primary_location"),
            "waste_type": waste_type,
            "severity": extraction.get("severity", "unknown"),
            "urgency": extraction.get("urgency", "unknown"),
            "geocode_status": geocode_status,
            "lat": geo_lat,
            "lng": geo_lng,
            "geocode_source": geocode_source,
            "confidence": confidence,
        })
        db.commit()
        log.info("WhatsApp report saved from %s", sender)
    finally:
        db.close()
