"""Opinion/analysis podcast episodes — the "what people think" angle,
via real human voices rather than scraped social media. Different from
fetch_news.py in one important way: we do NOT rewrite audio into our own
words (can't, without literally re-recording it) — episodes stream
directly from the publisher's own hosted audio file (the RSS <enclosure>
URL), the same way every podcast app works. Because we're relaying their
actual audio rather than replacing it with our own words, source
attribution + a link back is appropriate here — the opposite of the
no-attribution stance for text articles, and intentionally so.
"""
from __future__ import annotations

import html
import re
from typing import Any
from xml.etree import ElementTree

import requests

ITUNES_NS = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"

# name -> (rss url, show name, link to the show's page)
PODCASTS = {
    "guardian_todayinfocus": (
        "https://www.theguardian.com/news/series/todayinfocus/podcast.xml",
        "The Guardian — Today in Focus",
        "https://www.theguardian.com/news/series/todayinfocus",
    ),
    "bbc_globalnews": (
        "https://podcasts.files.bbci.co.uk/p02nq0gn.rss",
        "BBC — Global News Podcast",
        "https://www.bbc.co.uk/programmes/p02nq0gn",
    ),
    "nyt_thedaily": (
        "https://feeds.simplecast.com/54nAGcIl",
        "The New York Times — The Daily",
        "https://www.nytimes.com/column/the-daily",
    ),
}


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def _parse_feed(source: str, url: str, show_name: str, show_link: str, limit: int) -> list[dict[str, Any]]:
    try:
        resp = requests.get(url, headers={"User-Agent": "news-spike/0.1"}, timeout=10)
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)
    except Exception as exc:  # noqa: BLE001
        print(f"[podcast:{source}] fetch/parse failed: {exc}")
        return []

    episodes = []
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        description = _strip_html(item.findtext("description") or item.findtext(f"{ITUNES_NS}summary") or "")
        pub_date = (item.findtext("pubDate") or "").strip()
        guid = (item.findtext("guid") or item.findtext("link") or "").strip()
        if not title or not guid:
            continue

        enclosure = item.find("enclosure")
        audio_url = enclosure.get("url") if enclosure is not None else None
        if not audio_url:
            continue  # no playable audio, skip — this isn't optional for a "listen" feature

        duration = item.findtext(f"{ITUNES_NS}duration")
        image_el = item.find(f"{ITUNES_NS}image")
        image_url = image_el.get("href") if image_el is not None else None

        episodes.append(
            {
                "guid": f"podcast:{guid}",
                "source": source,
                "show_name": show_name,
                "show_link": show_link,
                "category": "OPINION",
                "title": html.unescape(title),
                "description": description,
                "audio_url": audio_url,
                "duration": duration,
                "image_url": image_url,
                "pub_date": pub_date,
            }
        )
    return episodes


def fetch_podcast_episodes(limit_per_show: int = 3) -> list[dict[str, Any]]:
    episodes = []
    for source, (url, show_name, show_link) in PODCASTS.items():
        episodes.extend(_parse_feed(source, url, show_name, show_link, limit_per_show))
    return episodes


if __name__ == "__main__":
    result = fetch_podcast_episodes(limit_per_show=2)
    print(f"Fetched {len(result)} episodes")
    for e in result:
        print(f"  - [{e['show_name']}] {e['title']} ({e['duration']}) -> {e['audio_url'][:60]}...")
