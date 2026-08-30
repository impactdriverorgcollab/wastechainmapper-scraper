"""
NLP extraction via Claude API.

Extracts structured waste-dumping intelligence from raw scraped text.
Uses claude-haiku for speed and cost efficiency on high-volume scraping.
Returns a typed dict; caller decides whether to write to DB.
"""

import json
import logging
from typing import TypedDict, Optional
import anthropic
from app.config import settings

log = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

EXTRACTION_SYSTEM = """You are a data extraction assistant for an environmental monitoring platform
tracking illegal waste dumping in Rivers State, Nigeria. Extract structured information from
Nigerian news articles and social media posts about waste and environmental issues."""

EXTRACTION_PROMPT = """Extract waste dumping information from the text below.

Return ONLY a valid JSON object with these fields:
- is_dumping_related (boolean): true if the text describes actual waste dumping, illegal disposal, or environmental pollution with a specific location
- location_mentions (array of strings): exact location names mentioned — communities, areas, LGAs, landmarks in Rivers State
- primary_location (string or null): the single most specific location mentioned (community or area name, not the state itself)
- waste_type (string): one of: municipal, industrial, medical, electronic, construction, mixed, unknown
- severity (string): one of: critical, high, moderate, low, unknown
- urgency (string): one of: immediate, soon, routine, unknown
- confidence (number 0.0-1.0): how confident are you this describes a real, geolocatable dumping incident?
- summary (string): 1-2 sentence summary of the incident

Text:
{text}"""


class ExtractionResult(TypedDict):
    is_dumping_related: bool
    location_mentions: list[str]
    primary_location: Optional[str]
    waste_type: str
    severity: str
    urgency: str
    confidence: float
    summary: str


_FALLBACK: ExtractionResult = {
    "is_dumping_related": False,
    "location_mentions": [],
    "primary_location": None,
    "waste_type": "unknown",
    "severity": "unknown",
    "urgency": "unknown",
    "confidence": 0.0,
    "summary": "",
}


def extract_from_text(text: str) -> ExtractionResult:
    # Truncate to stay well within context limits while preserving the most useful content.
    truncated = text[:5000]

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=EXTRACTION_SYSTEM,
            messages=[{
                "role": "user",
                "content": EXTRACTION_PROMPT.format(text=truncated),
            }],
        )
        raw = message.content[0].text.strip()

        # Strip markdown code fences if Claude wraps the JSON
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        result: ExtractionResult = json.loads(raw)
        return result

    except json.JSONDecodeError as exc:
        log.warning("Claude returned non-JSON: %s", exc)
        return _FALLBACK
    except anthropic.APIError as exc:
        log.error("Anthropic API error: %s", exc)
        return _FALLBACK


def waste_type_to_enum(value: str) -> str:
    mapping = {
        "municipal": "MUNICIPAL",
        "industrial": "INDUSTRIAL",
        "medical": "MEDICAL",
        "electronic": "ELECTRONIC",
        "construction": "CONSTRUCTION",
        "mixed": "MIXED",
    }
    return mapping.get(value.lower(), "UNKNOWN")
