"""
News scrapers for Rivers State waste/dumping coverage.

Sites targeted:
  - tidenewsonline.com  (Rivers State-focused; highest local relevance)
  - vanguardngr.com
  - punchng.com

Scraping approach: fetch each site's search results page for relevant keywords,
extract article title + summary + URL. Full article text is fetched separately.

NOTE: CSS selectors are as of mid-2026 and may drift. If a scraper returns 0 results,
inspect the live page and update the selectors below.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

KEYWORDS = [
    "illegal dumping Rivers State",
    "waste dumping Port Harcourt",
    "refuse dump Rivers",
    "environmental pollution Rivers State",
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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fetch(url: str, timeout: int = 15) -> Optional[BeautifulSoup]:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")
    except Exception as exc:
        log.warning("fetch failed %s: %s", url, exc)
        return None


def _fetch_article_text(url: str) -> str:
    soup = _fetch(url)
    if not soup:
        return ""
    # Generic: grab the largest <article> or <div class="content"> block
    for selector in ["article", ".entry-content", ".post-content", ".article-body", "main"]:
        el = soup.select_one(selector)
        if el:
            return el.get_text(separator=" ", strip=True)[:6000]
    return soup.get_text(separator=" ", strip=True)[:3000]


# ── The Tide News Online ──────────────────────────────────────────────────────

def scrape_tide_news(keyword: str = "illegal dumping Rivers State") -> list[ScrapedArticle]:
    """tidenewsonline.com — Rivers State daily."""
    results: list[ScrapedArticle] = []
    url = f"https://www.tidenewsonline.com/?s={keyword.replace(' ', '+')}"
    soup = _fetch(url)
    if not soup:
        return results

    # Tide uses a standard WordPress theme; articles are in .post or article tags
    for article in soup.select("article.post, .post-listing article")[:10]:
        title_el = article.select_one("h2 a, h3 a, .entry-title a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        summary_el = article.select_one(".entry-summary, .post-excerpt, p")
        summary = summary_el.get_text(strip=True)[:400] if summary_el else ""
        full = _fetch_article_text(href)
        results.append(ScrapedArticle(
            title=title, url=href, summary=summary,
            full_text=full or summary, published_at=None, source="tidenewsonline.com",
        ))

    log.info("Tide News: %d articles for '%s'", len(results), keyword)
    return results


# ── Vanguard ─────────────────────────────────────────────────────────────────

def scrape_vanguard(keyword: str = "illegal dumping Rivers State") -> list[ScrapedArticle]:
    """vanguardngr.com"""
    results: list[ScrapedArticle] = []
    url = f"https://www.vanguardngr.com/?s={keyword.replace(' ', '+')}"
    soup = _fetch(url)
    if not soup:
        return results

    for article in soup.select(".td_module_wrap, article.post")[:10]:
        title_el = article.select_one(".entry-title a, h3 a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        summary_el = article.select_one(".td-excerpt, .entry-summary")
        summary = summary_el.get_text(strip=True)[:400] if summary_el else ""
        full = _fetch_article_text(href)
        results.append(ScrapedArticle(
            title=title, url=href, summary=summary,
            full_text=full or summary, published_at=None, source="vanguardngr.com",
        ))

    log.info("Vanguard: %d articles for '%s'", len(results), keyword)
    return results


# ── Punch ────────────────────────────────────────────────────────────────────

def scrape_punch(keyword: str = "illegal dumping Rivers State") -> list[ScrapedArticle]:
    """punchng.com"""
    results: list[ScrapedArticle] = []
    url = f"https://punchng.com/?s={keyword.replace(' ', '+')}"
    soup = _fetch(url)
    if not soup:
        return results

    for article in soup.select("article.post, .post-block")[:10]:
        title_el = article.select_one("h2 a, h3 a, .post-title a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        summary_el = article.select_one(".entry-summary, p")
        summary = summary_el.get_text(strip=True)[:400] if summary_el else ""
        full = _fetch_article_text(href)
        results.append(ScrapedArticle(
            title=title, url=href, summary=summary,
            full_text=full or summary, published_at=None, source="punchng.com",
        ))

    log.info("Punch: %d articles for '%s'", len(results), keyword)
    return results


# ── Combined runner ───────────────────────────────────────────────────────────

def run_all_news_scrapers() -> list[ScrapedArticle]:
    articles: list[ScrapedArticle] = []
    for keyword in KEYWORDS[:2]:  # limit keywords per run to avoid rate-limiting
        articles.extend(scrape_tide_news(keyword))
        articles.extend(scrape_vanguard(keyword))
        articles.extend(scrape_punch(keyword))

    # Deduplicate by URL
    seen: set[str] = set()
    unique = []
    for a in articles:
        if a.url and a.url not in seen:
            seen.add(a.url)
            unique.append(a)

    log.info("News scrape total: %d unique articles", len(unique))
    return unique
