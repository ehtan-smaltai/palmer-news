"""Build the News UI: fetch articles, rewrite under the grounding rule,
match each against live Polymarket markets, render as a static page with
the matched market embedded directly into the article card — this is the
per-article overlay feature from the design doc (separate from the
standalone Prediction section in build_prediction_page.py).

Usage: python build_news_page.py
Output: output/news.html
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from fetch_news import fetch_news
from fetch_polymarket import fetch_polymarket_markets
from match_article_to_market import match_articles
from rewrite_news import rewrite_articles

load_dotenv()

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_FILE = OUTPUT_DIR / "news.html"


def _market_widget_html(m: dict) -> str:
    odds = ""
    if m.get("outcomes") and m.get("outcome_prices"):
        pairs = zip(m["outcomes"], m["outcome_prices"])
        odds = " · ".join(f"{html.escape(o)}: {float(p)*100:.0f}%" for o, p in pairs)
    title = html.escape(m["title"] or "")
    url = m.get("url") or "#"
    reason = html.escape(m.get("match_reason", ""))
    return f"""
    <div class="market-widget">
      <div class="market-label">Related prediction market</div>
      <a href="{url}" target="_blank" rel="noopener" class="market-title">{title}</a>
      <div class="market-odds">{odds}</div>
      <div class="market-reason">{reason}</div>
    </div>"""


def _article_card_html(a: dict) -> str:
    title = html.escape(a["title"])
    body = html.escape(a.get("rewritten") or a.get("description") or "")
    link = a.get("link") or "#"
    source = html.escape(a.get("source", ""))
    widget = _market_widget_html(a["matched_market"]) if a.get("matched_market") else ""
    return f"""
    <article class="card">
      <div class="source">{source}</div>
      <h3><a href="{link}" target="_blank" rel="noopener">{title}</a></h3>
      <p>{body}</p>
      {widget}
    </article>"""


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>News — spike output</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; max-width: 720px;
         margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 0.25rem; }}
  .meta {{ color: #666; font-size: 0.85rem; margin-bottom: 2rem; }}
  .card {{ border: 1px solid #e2e2e2; border-radius: 8px; padding: 1rem 1.25rem;
           margin-bottom: 1.25rem; }}
  .source {{ font-size: 0.7rem; text-transform: uppercase; color: #888;
             letter-spacing: 0.05em; }}
  h3 {{ margin: 0.25rem 0 0.5rem; font-size: 1.05rem; }}
  h3 a {{ color: #111; text-decoration: none; }}
  h3 a:hover {{ text-decoration: underline; }}
  p {{ font-size: 0.92rem; line-height: 1.5; color: #333; margin: 0; }}
  .market-widget {{ margin-top: 0.9rem; padding: 0.7rem 0.9rem; background: #f4f7ff;
                     border-left: 3px solid #1a56db; border-radius: 4px; }}
  .market-label {{ font-size: 0.65rem; text-transform: uppercase; color: #1a56db;
                    letter-spacing: 0.05em; margin-bottom: 0.2rem; }}
  .market-title {{ font-size: 0.88rem; font-weight: 600; color: #1a1a1a;
                    text-decoration: none; }}
  .market-title:hover {{ text-decoration: underline; }}
  .market-odds {{ font-size: 0.85rem; color: #1a56db; margin-top: 0.15rem; }}
  .market-reason {{ font-size: 0.75rem; color: #888; margin-top: 0.15rem; font-style: italic; }}
  .empty {{ color: #888; font-style: italic; }}
</style>
</head>
<body>
  <h1>News — spike output</h1>
  <div class="meta">Generated {generated_at} UTC. Rewrite grounded to \
RSS teaser text only (not full articles) — single-pass, no verify step yet. \
Market matches are LLM-judged against live Polymarket data at generation \
time.</div>
  {cards}
</body>
</html>
"""


def build() -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)

    print("Fetching news...")
    articles = fetch_news(limit_per_feed=6)
    print(f"  got {len(articles)} articles")

    print("Rewriting under grounding rule...")
    articles = rewrite_articles(articles)

    print("Fetching Polymarket markets for matching...")
    markets = fetch_polymarket_markets(limit=40)
    print(f"  got {len(markets)} markets")

    print("Matching articles to markets...")
    articles = match_articles(articles, markets)
    matched_count = sum(1 for a in articles if a.get("matched_market"))
    print(f"  {matched_count}/{len(articles)} articles matched a market")

    cards = "\n".join(_article_card_html(a) for a in articles) or '<div class="empty">No articles.</div>'

    html_out = PAGE_TEMPLATE.format(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        cards=cards,
    )
    OUTPUT_FILE.write_text(html_out, encoding="utf-8")
    print(f"Wrote {OUTPUT_FILE}")
    return OUTPUT_FILE


if __name__ == "__main__":
    build()
