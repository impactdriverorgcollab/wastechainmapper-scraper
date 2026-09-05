"""
News scrapers using RSS feeds — avoids 403 blocks from direct search-page scraping.

Sources:
  - Google News RSS  (keyword search, aggregates Vanguard / Punch / Tide / Guardian)
  - Vanguard RSS     (general feed, filtered by keywords)
  - Punch RSS        (general feed, filtered by keywords)
"""

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional
import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

KEYWORDS = [
    "illegal dumping Rivers State",
    "waste dumping Port Harcourt",
    "refuse dump Rivers",
    "environmental pollution Rivers State",
    "waste collection Rivers State",
    "refuse collection Port Harcourt",
    "waste evacuation Rivers",
    "clean-up Rivers State environment",
]

KEYWORD_FILTER = [
    "dump", "waste", "refuse", "pollution", "illegal dump",
    "sanitation", "sewage", "rivers state", "port harcourt",
    "collection", "evacuation", "clean-up", "cleanup", "remediation",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; WasteWatchBot/0.1; "
        "+https://github.com/juniorforge/wastewatch)"
    )
}


@dataclass
class ScrapedArticle:
    title: str
    url: str
    summary: str
    full_text: str
    published_at: Optional[datetime]
    source: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch_text(url: str, timeout: int = 20) -> Optional[str]:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception as exc:
        log.warning("fetch failed %s: %s", url, exc)
        return None


def _parse_rss(xml_text: str) -> list[dict]:
    """Return list of {title, link, description, pubDate} dicts from an RSS feed."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning("RSS parse error: %s", exc)
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = []
    for item in root.iter("item"):
        def _t(tag: str) -> str:
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        pub_raw = _t("pubDate")
        published_at = None
        if pub_raw:
            try:
                published_at = parsedate_to_datetime(pub_raw)
            except Exception:
                pass

        items.append({
            "title": _t("title"),
            "link": _t("link"),
            "description": _t("description"),
            "published_at": published_at,
        })
    return items


def _is_relevant(title: str, description: str) -> bool:
    combined = (title + " " + description).lower()
    return any(kw in combined for kw in KEYWORD_FILTER)


def _fetch_article_text(url: str) -> str:
    raw = _fetch_text(url, timeout=15)
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for selector in ["article", ".entry-content", ".post-content", ".article-body", "main"]:
        el = soup.select_one(selector)
        if el:
            return el.get_text(separator=" ", strip=True)[:6000]
    return soup.get_text(separator=" ", strip=True)[:3000]


# ── Google News RSS ───────────────────────────────────────────────────────────

def scrape_google_news(keyword: str) -> list[ScrapedArticle]:
    """
    Google News RSS aggregates Nigerian outlets without requiring auth.
    Results include Vanguard, Punch, Guardian, Channels, Tide, etc.
    """
    encoded = keyword.replace(" ", "+")
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-NG&gl=NG&ceid=NG:en"
    raw = _fetch_text(url)
    if not raw:
        return []

    items = _parse_rss(raw)
    results: list[ScrapedArticle] = []

    for item in items[:15]:
        title = item["title"]
        link = item["link"]
        description = BeautifulSoup(item["description"], "html.parser").get_text()

        if not _is_relevant(title, description):
            continue

        full = _fetch_article_text(link)
        results.append(ScrapedArticle(
            title=title,
            url=link,
            summary=description[:400],
            full_text=full or description,
            published_at=item["published_at"],
            source="google_news",
        ))

    log.info("Google News RSS: %d relevant articles for '%s'", len(results), keyword)
    return results


# ── Vanguard RSS ──────────────────────────────────────────────────────────────

def scrape_vanguard_rss() -> list[ScrapedArticle]:
    raw = _fetch_text("https://www.vanguardngr.com/feed/")
    if not raw:
        return []

    items = _parse_rss(raw)
    results: list[ScrapedArticle] = []

    for item in items[:50]:
        if not _is_relevant(item["title"], item["description"]):
            continue
        description = BeautifulSoup(item["description"], "html.parser").get_text()
        full = _fetch_article_text(item["link"])
        results.append(ScrapedArticle(
            title=item["title"],
            url=item["link"],
            summary=description[:400],
            full_text=full or description,
            published_at=item["published_at"],
            source="vanguardngr.com",
        ))

    log.info("Vanguard RSS: %d relevant articles", len(results))
    return results


# ── Punch RSS ─────────────────────────────────────────────────────────────────

def scrape_punch_rss() -> list[ScrapedArticle]:
    raw = _fetch_text("https://punchng.com/feed/")
    if not raw:
        return []

    items = _parse_rss(raw)
    results: list[ScrapedArticle] = []

    for item in items[:50]:
        if not _is_relevant(item["title"], item["description"]):
            continue
        description = BeautifulSoup(item["description"], "html.parser").get_text()
        full = _fetch_article_text(item["link"])
        results.append(ScrapedArticle(
            title=item["title"],
            url=item["link"],
            summary=description[:400],
            full_text=full or description,
            published_at=item["published_at"],
            source="punchng.com",
        ))

    log.info("Punch RSS: %d relevant articles", len(results))
    return results


# ── Combined runner ───────────────────────────────────────────────────────────

def run_all_news_scrapers() -> list[ScrapedArticle]:
    articles: list[ScrapedArticle] = []

    # Google News RSS — keyword-targeted, best signal-to-noise
    for keyword in KEYWORDS[:3]:
        articles.extend(scrape_google_news(keyword))

    # General RSS feeds — catch anything keyword search missed
    articles.extend(scrape_vanguard_rss())
    articles.extend(scrape_punch_rss())

    # Deduplicate by URL
    seen: set[str] = set()
    unique = []
    for a in articles:
        if a.url and a.url not in seen:
            seen.add(a.url)
            unique.append(a)

    log.info("News scrape total: %d unique articles", len(unique))
    return unique
