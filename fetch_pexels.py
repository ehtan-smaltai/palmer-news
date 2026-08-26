"""Fallback images for articles whose source RSS has no photo (Guardian,
Al Jazeera, CNN all lack BBC's media:thumbnail tag). Pexels stock photos —
unlike BBC's own CDN images, these are explicitly licensed for free reuse
(including commercial) with no attribution required, so there's no
sourcing/ToS concern here the way there is with news imagery.

Query is derived from the article's own significant words/category, not
hand-picked — same "boring is fine, no invented specifics" spirit as the
rest of the pipeline, just applied to image search terms instead of text.
"""
from __future__ import annotations

import os
from typing import Any

import requests

from corroboration import _significant_words
from store import get_cached_image, save_image

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


def _query_for(article: dict[str, Any]) -> str:
    words = list(_significant_words(f"{article['title']} {article.get('description', '')}"))
    if words:
        return " ".join(words[:3])
    return article.get("category", "news").lower()


def fetch_fallback_image(conn, article: dict[str, Any]) -> str | None:
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        return None

    query = _query_for(article)
    cached = get_cached_image(conn, query)
    if cached:
        return cached

    try:
        resp = requests.get(
            PEXELS_SEARCH_URL,
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            headers={"Authorization": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        if not photos:
            return None
        image_url = photos[0]["src"]["large"]
        save_image(conn, query, image_url)
        return image_url
    except Exception as exc:  # noqa: BLE001
        print(f"[pexels] search failed for query '{query}': {exc}")
        return None


if __name__ == "__main__":
    from store import get_conn

    conn = get_conn()
    test_article = {"title": "SpaceX launches new rocket", "description": "", "category": "TECHNOLOGY"}
    print(fetch_fallback_image(conn, test_article))
