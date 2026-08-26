"""The real pipeline entrypoint. Each run:

1. Fetches all news sources + live Polymarket markets. (Finance/stock
   quotes are fetched separately by fetch_finance.py but not wired into
   this run right now — see note below.)
2. Clusters articles covering the same real-world event across outlets
   (corroboration.cluster_articles), and gates volatile/single-source
   stories (evaluate_cluster).
3. Only genuinely NEW stories (primary guid not already in the local store)
   get the expensive treatment: a detailed, multi-source-grounded article
   (detail_article.py) with a verify pass, then market matching. Already-
   seen stories are skipped (no repeat LLM billing) but their held-back
   status is refreshed in case a second source has since corroborated them.
4. Persists everything to SQLite (store.py) and writes a per-story detail
   page to output/articles/{slug}.html — the homepage links there now
   (internal permalink), not to the source outlet.
5. Renders the homepage from accumulated history and writes a run-log line
   for basic monitoring.

Usage: python run_pipeline.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Windows console defaults to a codepage (cp1252 etc.) that can't represent
# most non-ASCII characters — confirmed crash 2026-08-26 on a Czech name
# from sports coverage (UnicodeEncodeError killed the whole run mid-tick).
# With global sports/entertainment sources now in the mix, non-ASCII names
# are routine, not an edge case — reconfigure stdout/stderr to UTF-8 with
# a safe fallback so a print() call can never crash the pipeline.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH)

from build_site import (
    ARTICLE_CATEGORIES,
    render_page,
    write_article_page,
    write_category_page,
    write_llms_txt,
    write_opinion_page,
    write_page,
    write_prediction_page,
    write_robots_txt,
    write_sitemap,
)
from corroboration import cluster_articles, evaluate_cluster
from detail_article import build_detail_article, select_primary
from fetch_news import fetch_news
from fetch_pexels import fetch_fallback_image
from fetch_podcasts import fetch_podcast_episodes
from fetch_polymarket import fetch_polymarket_markets
from match_article_to_market import match_article
from rewrite_news import rewrite_article
from store import (
    existing_guids,
    existing_podcast_guids,
    get_conn,
    recent_articles,
    recent_podcast_episodes,
    save_article,
    save_podcast_episode,
)

# Finance (stock quotes) is deliberately not fetched/rendered right now —
# founder feedback: no point showing plain numbers until there's a real
# live-market view worth building. fetch_finance.py still works standalone
# if this gets revisited.

RUN_LOG = Path(__file__).parent / "data" / "run_log.jsonl"

# Polymarket Gamma API tag ids (numeric — the string tag/tag_slug params
# don't actually filter, confirmed 2026-08-26). Found via /tags sorted by
# id; these are the ones with live markets as of that date.
POLYMARKET_TAG_SPORTS = 1
POLYMARKET_TAG_MOVIES = 53
POLYMARKET_TAG_MUSIC = 100


def _to_db_row(a: dict, matched_market: dict | None, corro: dict) -> dict:
    return {
        "guid": a["guid"],
        "source": a["source"],
        "category": a["category"],
        "title": a["title"],
        "description": a.get("description"),
        "link": a.get("link"),
        "image_url": a.get("image_url"),
        "pub_date": a.get("pub_date"),
        "rewritten_title": a.get("rewritten_title"),
        "rewritten_summary": a.get("rewritten"),
        "detail_body": a.get("detail_body"),
        "slug": a.get("slug"),
        "source_count": a.get("source_count", 1),
        "verify_status": a.get("verify_status", "not_attempted"),
        "corroborated": int(corro["corroborated"]),
        "held_back": int(corro["held_back"]),
        "hold_reason": corro["hold_reason"],
        "matched_market_json": json.dumps(matched_market) if matched_market else None,
        "first_seen": a.get("first_seen", time.time()),
    }


def run(sources: list[str] | None = None) -> dict:
    """`sources`, if given, restricts this run to just those feed names —
    see scheduler_loop.py's staggered scheduling. Matching, rendering, and
    all category/SEO pages still run every call regardless, so whatever
    this tick's sources bring in shows up immediately."""
    conn = get_conn()
    started_at = time.time()
    stats = {"fetched": 0, "clusters": 0, "new_stories": 0, "held_back": 0,
              "detail_generated": 0, "verify_failed": 0, "matched": 0,
              "skipped_existing": 0, "fallback_images": 0, "new_episodes": 0}

    print(f"Fetching news from {sources or 'all'} sources...")
    fetched = fetch_news(limit_per_feed=8, sources=sources)
    stats["fetched"] = len(fetched)
    print(f"  {len(fetched)} articles across {len({a['source'] for a in fetched})} feeds")

    print("Clustering into stories...")
    clusters = cluster_articles(fetched)
    stats["clusters"] = len(clusters)
    print(f"  {len(fetched)} articles -> {len(clusters)} distinct stories")

    print("Fetching Polymarket markets...")
    # Plain top-volume-overall is dominated by politics/macro/crypto —
    # confirmed 2026-08-26 it was starving Sports/Entertainment articles of
    # real match candidates. Combine it with category-tagged pools so those
    # articles have something relevant to match against. Deduped by id;
    # order preserved (general pool first) so matching's index-based
    # response still lines up.
    general = fetch_polymarket_markets(limit=80)
    sports = fetch_polymarket_markets(limit=30, tag_id=POLYMARKET_TAG_SPORTS)
    movies = fetch_polymarket_markets(limit=15, tag_id=POLYMARKET_TAG_MOVIES)
    music = fetch_polymarket_markets(limit=15, tag_id=POLYMARKET_TAG_MUSIC)

    seen_ids = set()
    markets = []
    for pool in (general, sports, movies, music):
        for m in pool:
            if m["id"] not in seen_ids:
                seen_ids.add(m["id"])
                markets.append(m)
    print(f"  {len(markets)} markets ({len(general)} general + {len(sports)} sports + "
          f"{len(movies)} movies + {len(music)} music, deduped)")

    already_seen = existing_guids(conn)

    for cluster in clusters:
        corro = evaluate_cluster(cluster)
        primary_guid = select_primary(cluster)["guid"]

        if corro["held_back"]:
            stats["held_back"] += 1

        if primary_guid in already_seen:
            stats["skipped_existing"] += 1
            conn.execute(
                "UPDATE articles SET corroborated = ?, held_back = ?, hold_reason = ? WHERE guid = ?",
                (int(corro["corroborated"]), int(corro["held_back"]), corro["hold_reason"], primary_guid),
            )
            conn.commit()
            continue

        stats["new_stories"] += 1
        if corro["held_back"]:
            primary = select_primary(cluster)
            primary["first_seen"] = time.time()
            save_article(conn, _to_db_row(primary, None, corro))
            continue

        story = build_detail_article(cluster)
        story["first_seen"] = time.time()
        stats["detail_generated"] += 1

        if not story.get("image_url"):
            fallback_img = fetch_fallback_image(conn, story)
            if fallback_img:
                story["image_url"] = fallback_img
                story["image_is_fallback"] = True
                stats["fallback_images"] = stats.get("fallback_images", 0) + 1
        if story.get("verify_status") == "failed":
            stats["verify_failed"] += 1

        matched_market = match_article(story, markets)
        if matched_market:
            stats["matched"] += 1

        save_article(conn, _to_db_row(story, matched_market, corro))

        if story.get("detail_body") and story.get("slug"):
            write_article_page(story, matched_market)

    print("Fetching podcast episodes...")
    already_seen_podcasts = existing_podcast_guids(conn)
    fetched_episodes = fetch_podcast_episodes(limit_per_show=3)
    new_episode_count = 0
    for ep in fetched_episodes:
        if ep["guid"] in already_seen_podcasts:
            continue
        new_episode_count += 1
        ep = rewrite_article(ep)  # same grounding+verify pass as news, just for the blurb
        ep["first_seen"] = time.time()
        save_podcast_episode(conn, {
            "guid": ep["guid"], "source": ep["source"], "show_name": ep["show_name"],
            "show_link": ep["show_link"], "title": ep["title"], "description": ep.get("description"),
            "rewritten_title": ep.get("rewritten_title"), "rewritten_summary": ep.get("rewritten"),
            "audio_url": ep["audio_url"], "duration": ep.get("duration"), "image_url": ep.get("image_url"),
            "pub_date": ep.get("pub_date"), "verify_status": ep.get("verify_status", "not_attempted"),
            "first_seen": ep["first_seen"],
        })
    stats["new_episodes"] = new_episode_count
    print(f"  {len(fetched_episodes)} episodes fetched, {new_episode_count} new")
    write_opinion_page(recent_podcast_episodes(conn, limit=20))

    print("Rendering homepage from accumulated history...")
    articles_for_render = recent_articles(conn, limit=40)
    html_out = render_page(articles_for_render, markets, finance_quotes=None)
    out_path = write_page(html_out)

    print("Rendering category pages...")
    for category in ARTICLE_CATEGORIES:
        cat_articles = recent_articles(conn, limit=30, category=category)
        write_category_page(category, cat_articles)
    write_prediction_page(markets)

    print("Writing SEO files (robots.txt, sitemap.xml, llms.txt)...")
    write_robots_txt()
    write_sitemap(articles_for_render)
    write_llms_txt()

    stats["duration_s"] = round(time.time() - started_at, 1)
    stats["rendered_from_history"] = len(articles_for_render)
    stats["output"] = str(out_path)
    stats["ts"] = datetime.now(timezone.utc).isoformat()

    RUN_LOG.parent.mkdir(exist_ok=True)
    with open(RUN_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(stats) + "\n")

    print(f"\nRun complete in {stats['duration_s']}s: {stats}")
    return stats


if __name__ == "__main__":
    run()
