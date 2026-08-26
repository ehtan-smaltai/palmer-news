"""Pull recent articles from multiple RSS feeds across sources, each tagged
with its Palmer News category (Market / Finance / Technology) and its own
"trust source" name for corroboration purposes (see corroboration.py).

Network notes (confirmed 2026-08-26):
- BBC, Guardian, Al Jazeera: all directly reachable, no relay needed.
- CNN (rss.cnn.com https): SSL handshake fails from this network specifically
  — kept in the config but expected to fail gracefully; not worth chasing
  further since Guardian + Al Jazeera already give real cross-source
  corroboration coverage for MARKET/world news.

Guardian's RSS <description> includes a genuine excerpt (several sentences,
with HTML markup), not just a one-line teaser like BBC/Al Jazeera — richer
grounding material for the same "only what's literally in the source text"
rewrite rule, no scraping needed.
"""
from __future__ import annotations

import html
import re
from typing import Any
from xml.etree import ElementTree

import requests

MEDIA_NS = "{http://search.yahoo.com/mrss/}"

# name -> (url, category, corroboration-source-name)
FEEDS = {
    "bbc_world": ("https://feeds.bbci.co.uk/news/world/rss.xml", "MARKET", "bbc"),
    "bbc_business": ("https://feeds.bbci.co.uk/news/business/rss.xml", "FINANCE", "bbc"),
    "bbc_technology": ("https://feeds.bbci.co.uk/news/technology/rss.xml", "TECHNOLOGY", "bbc"),
    "guardian_world": ("https://www.theguardian.com/world/rss", "MARKET", "guardian"),
    "aljazeera": ("https://www.aljazeera.com/xml/rss/all.xml", "MARKET", "aljazeera"),
    "cnn_world": ("https://rss.cnn.com/rss/cnn_world.rss", "MARKET", "cnn"),
}


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def _parse_feed(source: str, url: str, category: str, corro_source: str, limit: int) -> list[dict[str, Any]]:
    try:
        resp = requests.get(url, headers={"User-Agent": "news-spike/0.1"}, timeout=10)
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)
    except Exception as exc:  # noqa: BLE001
        print(f"[news:{source}] fetch/parse failed: {exc}")
        return []

    items = []
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        description = _strip_html(item.findtext("description") or "")
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        if not title or not link:
            continue

        image_url = None
        thumb = item.find(f"{MEDIA_NS}thumbnail")
        if thumb is not None:
            image_url = thumb.get("url")

        items.append(
            {
                "guid": link,  # link is stable and unique enough for dedup
                "source": source,
                "corro_source": corro_source,
                "category": category,
                "title": html.unescape(title),
                "description": description,
                "link": link,
                "pub_date": pub_date,
                "image_url": image_url,
            }
        )
    return items


def fetch_news(limit_per_feed: int = 8) -> list[dict[str, Any]]:
    articles = []
    for source, (url, category, corro_source) in FEEDS.items():
        articles.extend(_parse_feed(source, url, category, corro_source, limit_per_feed))
    return articles


if __name__ == "__main__":
    result = fetch_news(limit_per_feed=5)
    print(f"Fetched {len(result)} articles")
    for a in result[:8]:
        print(f"  - [{a['source']}/{a['category']}] {a['title']}")
