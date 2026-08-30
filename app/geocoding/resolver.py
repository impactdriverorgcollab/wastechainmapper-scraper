"""
Geocoding pipeline for extracted location mentions.

Priority order:
1. Exact match in local gazetteer table
2. Fuzzy match in local gazetteer (rapidfuzz, threshold 70)
3. Nominatim (OSM) with Rivers State bias
4. Log as UNRESOLVED for manual gazetteer enrichment

All Nominatim requests include a Referer header per their usage policy.
Rate limit: 1 request/second (enforced by the caller via APScheduler intervals).
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional
import httpx
from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {
    "User-Agent": "WasteWatch/0.1 (juniorforge68@gmail.com)",
    "Referer": "https://github.com/juniorforge/wastewatch",
}
# Bias Nominatim results towards Rivers State bounding box
RIVERS_STATE_VIEWBOX = "6.5,4.2,7.9,5.5"  # min_lng,min_lat,max_lng,max_lat


@dataclass
class GeoResult:
    latitude: float
    longitude: float
    source: str          # "gazetteer_exact" | "gazetteer_fuzzy" | "nominatim"
    gazetteer_id: Optional[str] = None
    display_name: Optional[str] = None


def resolve_location(
    location_text: str,
    db: Session,
    lga_hint: Optional[str] = None,
) -> Optional[GeoResult]:
    """
    Main entry point. Returns None if the location cannot be resolved.
    The caller sets geocode_status based on the returned GeoResult.source.
    """
    if not location_text or len(location_text.strip()) < 3:
        return None

    # 1. Exact gazetteer match
    result = _gazetteer_exact(location_text, db, lga_hint)
    if result:
        return result

    # 2. Fuzzy gazetteer match
    result = _gazetteer_fuzzy(location_text, db, lga_hint)
    if result:
        return result

    # 3. Nominatim fallback
    result = _nominatim(location_text)
    return result


# ── Gazetteer exact ──────────────────────────────────────────────────────────

def _gazetteer_exact(name: str, db: Session, lga_hint: Optional[str]) -> Optional[GeoResult]:
    from sqlalchemy import text
    query = text("""
        SELECT id, centroid_lat, centroid_lng
        FROM gazetteer
        WHERE LOWER(community_name) = LOWER(:name)
          AND centroid IS NOT NULL
          {lga_clause}
        LIMIT 1
    """.format(lga_clause="AND LOWER(lga) = LOWER(:lga)" if lga_hint else ""))

    params = {"name": name.strip()}
    if lga_hint:
        params["lga"] = lga_hint

    row = db.execute(query, params).fetchone()
    if not row:
        # Try alias match
        alias_query = text("""
            SELECT id, centroid_lat, centroid_lng
            FROM gazetteer
            WHERE :name = ANY(aliases)
              AND centroid IS NOT NULL
            LIMIT 1
        """)
        row = db.execute(alias_query, {"name": name.strip()}).fetchone()

    if row and row.centroid_lat and row.centroid_lng:
        return GeoResult(
            latitude=row.centroid_lat,
            longitude=row.centroid_lng,
            source="gazetteer_exact",
            gazetteer_id=str(row.id),
        )
    return None


# ── Gazetteer fuzzy ──────────────────────────────────────────────────────────

def _gazetteer_fuzzy(name: str, db: Session, lga_hint: Optional[str]) -> Optional[GeoResult]:
    from sqlalchemy import text
    query = text("""
        SELECT id, community_name, centroid_lat, centroid_lng, aliases
        FROM gazetteer
        WHERE centroid IS NOT NULL
          {lga_clause}
    """.format(lga_clause="AND LOWER(lga) = LOWER(:lga)" if lga_hint else ""))

    params = {"lga": lga_hint} if lga_hint else {}
    rows = db.execute(query, params).fetchall()

    if not rows:
        return None

    # Build candidate list: community_name + aliases
    candidates: dict[str, tuple] = {}
    for row in rows:
        key = row.community_name
        candidates[key] = row
        if row.aliases:
            for alias in row.aliases:
                candidates[alias] = row

    match = process.extractOne(name, list(candidates.keys()), scorer=fuzz.token_sort_ratio)
    if not match or match[1] < 70:
        return None

    row = candidates[match[0]]
    if not row.centroid_lat or not row.centroid_lng:
        return None

    log.debug("Fuzzy gazetteer: '%s' → '%s' (score %d)", name, match[0], match[1])
    return GeoResult(
        latitude=row.centroid_lat,
        longitude=row.centroid_lng,
        source="gazetteer_fuzzy",
        gazetteer_id=str(row.id),
        display_name=row.community_name,
    )


# ── Nominatim ────────────────────────────────────────────────────────────────

_last_nominatim_call: float = 0.0


def _nominatim(location_text: str) -> Optional[GeoResult]:
    global _last_nominatim_call

    # Enforce 1 req/s per Nominatim usage policy
    elapsed = time.time() - _last_nominatim_call
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)

    query = f"{location_text}, Rivers State, Nigeria"
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "viewbox": RIVERS_STATE_VIEWBOX,
        "bounded": 0,       # allow results outside viewbox if nothing found inside
        "countrycodes": "ng",
    }

    try:
        r = httpx.get(NOMINATIM_URL, params=params, headers=NOMINATIM_HEADERS, timeout=10)
        _last_nominatim_call = time.time()
        r.raise_for_status()
        data = r.json()

        if not data:
            log.info("Nominatim: no result for '%s'", location_text)
            return None

        hit = data[0]
        lat = float(hit["lat"])
        lng = float(hit["lon"])

        # Sanity-check: result should be in or near Rivers State
        if not (4.0 <= lat <= 6.0 and 6.0 <= lng <= 8.5):
            log.info("Nominatim: result outside Rivers State bounds for '%s'", location_text)
            return None

        return GeoResult(
            latitude=lat,
            longitude=lng,
            source="nominatim",
            display_name=hit.get("display_name"),
        )

    except Exception as exc:
        log.warning("Nominatim error for '%s': %s", location_text, exc)
        return None
