"""Render module for the Palmer News site. Rendering only — fetching,
dedup, corroboration, and persistence live in run_pipeline.py now.

BASE_URL is a placeholder — swap it for the real domain before this is
actually deployed publicly. It's only used for canonical links, sitemap.xml,
and robots.txt (all meaningless without a real, stable domain), so nothing
breaks locally while it's still a placeholder — those three things just
won't be correct until it's updated.
"""
from __future__ import annotations

import email.utils
import html
import re
from datetime import datetime, timezone
from pathlib import Path

SITE_NAME = "PALMER NEWS"
BASE_URL = "https://example.com"  # placeholder — set the real domain before going live

CATEGORY_PAGES = {
    "MARKET": "market.html",
    "FINANCE": "finance.html",
    "TECHNOLOGY": "technology.html",
    "PREDICTION": "prediction.html",
}

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_FILE = OUTPUT_DIR / "index.html"
ARTICLES_DIR = OUTPUT_DIR / "articles"

_BBC_WIDTH_RE = re.compile(r"/ace/standard/\d+/")


def _bbc_resize(url: str, width: int) -> str:
    """BBC's RSS thumbnail is a tiny 240px render. Their own ichef CDN
    serves larger renditions of the exact same image just by swapping the
    width segment in the URL — still their asset, their CDN, just a bigger
    size instead of the RSS-default thumbnail."""
    if not _BBC_WIDTH_RE.search(url):
        return url
    return _BBC_WIDTH_RE.sub(f"/ace/standard/{width}/", url)


def _img_html(a: dict, css_class: str, width: int) -> str:
    url = a.get("image_url")
    if not url:
        return ""
    url = _bbc_resize(url, width)
    alt = html.escape(a["title"])
    return f'<img class="{css_class}" src="{html.escape(url)}" alt="{alt}" loading="lazy">'


def _parse_when(a: dict) -> datetime | None:
    """Prefer the source's own pub_date (RFC 822, from RSS); fall back to
    first_seen (our own ingestion time) if that's missing or unparseable."""
    pub_date = a.get("pub_date")
    if pub_date:
        try:
            dt = email.utils.parsedate_to_datetime(pub_date)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (TypeError, ValueError):
            pass
    first_seen = a.get("first_seen")
    if first_seen:
        return datetime.fromtimestamp(first_seen, tz=timezone.utc)
    return None


def _time_ago(a: dict) -> str:
    when = _parse_when(a)
    if not when:
        return ""
    delta = datetime.now(timezone.utc) - when
    seconds = delta.total_seconds()
    if seconds < 3600:
        return f"{max(1, int(seconds // 60))} MIN AGO"
    if seconds < 86400:
        return f"{int(seconds // 3600)} HR AGO"
    return f"{int(seconds // 86400)} DAY(S) AGO"


def _iso_when(a: dict) -> str:
    when = _parse_when(a)
    return when.isoformat() if when else ""


def _market_odds_str(m: dict) -> str:
    if m.get("outcomes") and m.get("outcome_prices"):
        pairs = list(zip(m["outcomes"], m["outcome_prices"]))
        top = max(pairs, key=lambda p: float(p[1]))
        return f"{float(top[1]) * 100:.0f}%"
    return "—"


def _markets_strip_html(markets: list[dict]) -> str:
    cells = []
    for m in markets[:4]:
        title = html.escape(m["title"] or "")
        odds = _market_odds_str(m)
        cells.append(f"""
      <div class="mkt-cell">
        <div class="mkt-name">{title}</div>
        <div class="mkt-value">{odds}</div>
      </div>""")
    return "\n".join(cells)


def _market_widget_html(m: dict) -> str:
    odds = ""
    if m.get("outcomes") and m.get("outcome_prices"):
        pairs = zip(m["outcomes"], m["outcome_prices"])
        odds = " &nbsp;·&nbsp; ".join(f"{html.escape(o)} {float(p) * 100:.0f}%" for o, p in pairs)
    title = html.escape(m["title"] or "")
    url = m.get("url") or "#"
    return f"""
      <div class="prediction-tag">
        <span class="prediction-label">PREDICTION</span>
        <a href="{url}" target="_blank" rel="noopener">{title}</a>
        <span class="prediction-odds">{odds}</span>
      </div>"""


def _permalink(a: dict, prefix: str = "") -> str | None:
    slug = a.get("slug")
    return f"{prefix}articles/{slug}.html" if slug else None


def _article_html(a: dict, size: str, link_prefix: str = "") -> str:
    """size: 'hero' | 'medium' | 'small'. Hosted fully on our own page (no
    reroute) — headlines are the Bedrock-rewritten version where available.
    No per-article category tag (removed per founder feedback — the nav
    already carries category, no need to repeat it per card); a timestamp
    replaces it instead."""
    title = html.escape(a.get("rewritten_title") or a["title"])
    dek = html.escape(a.get("rewritten_summary") or a.get("rewritten") or a.get("description") or "")
    widget = _market_widget_html(a["matched_market"]) if a.get("matched_market") else ""
    link = _permalink(a, link_prefix)
    title_html = f'<a href="{link}">{title}</a>' if link else title
    time_html = f'<time datetime="{_iso_when(a)}">{_time_ago(a)}</time>' if _time_ago(a) else ""

    if size == "hero":
        img = _img_html(a, "hero-img", 1600)
        img_html = f'<a href="{link}">{img}</a>' if link and img else img
        return f"""
        <div class="hero-story">
          {img_html}
          <div class="meta-line">{time_html}</div>
          <h1>{title_html}</h1>
          <p class="dek">{dek}</p>
          {widget}
        </div>"""
    if size == "medium":
        img = _img_html(a, "medium-img", 480)
        img_html = f'<a href="{link}">{img}</a>' if link and img else img
        return f"""
        <div class="story-medium">
          {img_html}
          <div class="meta-line">{time_html}</div>
          <h3>{title_html}</h3>
          <p class="dek-small">{dek}</p>
          {widget}
        </div>"""
    return f"""
        <div class="story-small">
          <div class="meta-line">{time_html}</div>
          <h4>{title_html}</h4>
          {widget}
        </div>"""


SHARED_CSS = """
  :root {
    --bg: #faf9f6; --ink: #17171a; --rule: #d8d5cd; --accent: #b3121c;
    --muted: #6b6862; --strip-bg: #14161a;
  }
  * { box-sizing: border-box; }
  body { background: var(--bg); color: var(--ink); margin: 0;
    font-family: Georgia, 'Times New Roman', serif; }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 0 1.5rem; }
  .topbar { display: flex; justify-content: space-between; align-items: center;
    padding: 0.9rem 0; font-size: 0.72rem; letter-spacing: 0.08em;
    color: var(--muted); border-bottom: 1px solid var(--rule); }
  .masthead { text-align: center; padding: 2.2rem 0 1.4rem; }
  .masthead h1, .masthead a { font-family: 'Playfair Display', Georgia, serif;
    font-weight: 900; font-size: clamp(2.6rem, 7vw, 5rem);
    letter-spacing: 0.02em; margin: 0; color: var(--ink); text-decoration: none; }
  nav.catnav { display: flex; justify-content: center; gap: 2rem;
    padding: 0.9rem 0; border-top: 2px solid var(--ink);
    border-bottom: 1px solid var(--rule); font-size: 0.78rem;
    letter-spacing: 0.12em; font-family: 'JetBrains Mono', monospace; }
  nav.catnav a { color: var(--ink); text-decoration: none; }
  nav.catnav a:hover, nav.catnav a.active { color: var(--accent); }
  .mkt-strip { background: var(--strip-bg); color: #fff; padding: 1.2rem 0; }
  .mkt-strip-inner { display: flex; flex-wrap: wrap; gap: 1.5rem; }
  .mkt-cell { flex: 1 1 220px; padding: 0 1.2rem; border-left: 1px solid #333; }
  .mkt-cell:first-child { border-left: none; }
  .mkt-name { font-family: 'JetBrains Mono', monospace; font-size: 0.68rem;
    letter-spacing: 0.03em; color: #9a9a9a; text-transform: uppercase;
    margin-bottom: 0.4rem; line-height: 1.4; }
  .mkt-value { font-family: 'JetBrains Mono', monospace; font-weight: 700;
    font-size: 1.6rem; }
  .meta-line { font-family: 'JetBrains Mono', monospace; font-size: 0.68rem;
    color: var(--muted); letter-spacing: 0.05em; margin-bottom: 0.4rem; }
  .hero-section { display: grid; grid-template-columns: 2fr 1fr; gap: 3rem;
    padding: 2.5rem 0; border-bottom: 1px solid var(--rule); }
  .hero-img { width: 100%; height: 320px; object-fit: cover; margin-bottom: 1rem;
    filter: grayscale(15%); }
  .medium-img { width: 100%; height: 160px; object-fit: cover; margin-bottom: 0.7rem;
    filter: grayscale(15%); }
  .hero-story h1 { font-family: 'Playfair Display', serif; font-size: 2.2rem;
    line-height: 1.15; margin: 0 0 0.6rem; }
  h1 a, h3 a, h4 a { color: var(--ink); text-decoration: none; }
  h1 a:hover, h3 a:hover, h4 a:hover { text-decoration: underline; }
  .hero-img, .medium-img { display: block; }
  a:has(> .hero-img), a:has(> .medium-img) { border: none; }
  .dek { font-size: 1.02rem; color: #333; line-height: 1.55; margin: 0 0 0.8rem; }
  .side-list { border-left: 1px solid var(--rule); padding-left: 1.6rem; }
  .side-list h3.section-label { font-size: 0.7rem; font-family: 'JetBrains Mono', monospace;
    letter-spacing: 0.1em; color: var(--muted); margin: 0 0 1rem; }
  .story-small { padding: 0.8rem 0; border-bottom: 1px solid var(--rule); }
  .story-small:last-child { border-bottom: none; }
  .story-small h4 { margin: 0.2rem 0 0; font-size: 0.98rem; font-weight: normal;
    font-family: Georgia, serif; }
  .grid-section { padding: 2.5rem 0; }
  .grid-section > h2 { font-family: 'Playfair Display', serif; font-size: 1.5rem;
    margin: 0 0 1.5rem; }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 2.2rem; }
  .story-medium h3 { font-family: Georgia, serif; font-size: 1.15rem;
    line-height: 1.3; margin: 0.2rem 0 0.5rem; }
  .dek-small { font-size: 0.88rem; color: #444; line-height: 1.5; margin: 0; }
  .prediction-tag { margin-top: 0.7rem; padding: 0.55rem 0.7rem; background: #fdf1ee;
    border-left: 3px solid var(--accent); font-size: 0.78rem; }
  .prediction-label { font-family: 'JetBrains Mono', monospace; font-size: 0.6rem;
    letter-spacing: 0.08em; color: var(--accent); margin-right: 0.5rem; }
  .prediction-tag a { color: var(--ink); text-decoration: none; font-weight: 600; }
  .prediction-tag a:hover { text-decoration: underline; }
  .prediction-odds { display: block; margin-top: 0.2rem; color: var(--accent);
    font-family: 'JetBrains Mono', monospace; font-weight: 600; }
  .pred-table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
  .pred-table th { text-align: left; font-family: 'JetBrains Mono', monospace;
    font-size: 0.68rem; letter-spacing: 0.05em; color: var(--muted);
    text-transform: uppercase; padding: 0.5rem; border-bottom: 1px solid var(--ink); }
  .pred-table td { padding: 0.6rem 0.5rem; border-bottom: 1px solid var(--rule);
    font-size: 0.9rem; }
  .pred-table a { color: var(--ink); text-decoration: none; }
  .pred-table a:hover { text-decoration: underline; }
  footer { border-top: 2px solid var(--ink); padding: 1.5rem 0; margin-top: 2rem;
    font-size: 0.7rem; color: var(--muted); font-family: 'JetBrains Mono', monospace;
    text-align: center; }
  @media (max-width: 860px) {
    .hero-section { grid-template-columns: 1fr; }
    .grid { grid-template-columns: 1fr; }
    .mkt-cell { flex: 1 1 45%; border-left: none; }
  }
"""


def _head_html(title: str, description: str, canonical_path: str, og_image: str | None = None,
               extra_meta: str = "") -> str:
    canonical = f"{BASE_URL}/{canonical_path}"
    og_image_tag = f'<meta property="og:image" content="{html.escape(og_image)}">' if og_image else ""
    return f"""<meta charset="utf-8">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description)}">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(description)}">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:url" content="{canonical}">
{og_image_tag}
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,600;0,700;0,900;1,600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
{extra_meta}
<style>{SHARED_CSS}</style>"""


def _nav_html(active: str | None = None, prefix: str = "") -> str:
    links = []
    for name, href in CATEGORY_PAGES.items():
        cls = ' class="active"' if name == active else ""
        links.append(f'<a href="{prefix}{href}"{cls}>{name}</a>')
    return "\n    ".join(links)


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
{head}
</head>
<body>

  <div class="wrap topbar">
    <div>{today}</div>
  </div>

  <div class="masthead"><a href="index.html">{site_name}</a></div>

  <nav class="catnav">
    {nav_links}
  </nav>

  <div class="mkt-strip">
    <div class="wrap mkt-strip-inner">
      {markets_strip}
    </div>
  </div>

  <div class="wrap hero-section">
    {hero_html}
    <div class="side-list">
      <h3 class="section-label">TOP STORIES</h3>
      {side_html}
    </div>
  </div>

  <div class="wrap grid-section">
    <h2>{grid_heading}</h2>
    <div class="grid">
      {grid_html}
    </div>
  </div>

  <footer class="wrap">
    Generated {generated_at} UTC &nbsp;·&nbsp; News: BBC/Guardian/Al Jazeera RSS \
&nbsp;·&nbsp; Predictions: Polymarket (live) &nbsp;·&nbsp; Rewrite: Bedrock, \
grounded + verified &nbsp;·&nbsp; This is a development spike, not a \
published site.
  </footer>

</body>
</html>
"""


def render_page(articles: list[dict], markets: list[dict], finance_quotes: list[dict] | None = None) -> str:
    """Pure rendering: takes already-fetched/processed data, returns HTML.
    `finance_quotes` is accepted but not rendered (Finance strip removed
    per founder feedback until there's a real live-market view worth
    showing, not just numbers) — kept as a parameter so callers don't need
    to change, just pass None/[] and nothing breaks."""
    matched_first = sorted(articles, key=lambda a: a.get("matched_market") is None)
    hero = matched_first[0] if matched_first else None
    side = matched_first[1:5]
    grid = matched_first[5:14]

    hero_html = _article_html(hero, "hero") if hero else '<div class="hero-story"><p>No stories fetched.</p></div>'
    side_html = "\n".join(_article_html(a, "small") for a in side)
    grid_html = "\n".join(_article_html(a, "medium") for a in grid)
    markets_strip = _markets_strip_html(markets) if markets else '<div class="mkt-cell"><div class="mkt-name">NO DATA</div></div>'

    head = _head_html(
        title=f"{SITE_NAME} — News, Triangulated with Prediction Markets",
        description="Palmer News pairs AI-synthesized news coverage with live prediction-market "
                     "odds and social signal — an automated, transparently-generated news platform.",
        canonical_path="index.html",
        og_image=hero.get("image_url") if hero else None,
    )

    return PAGE_TEMPLATE.format(
        head=head,
        today=datetime.now(timezone.utc).strftime("%A, %B %d, %Y").upper(),
        site_name=SITE_NAME,
        nav_links=_nav_html(),
        markets_strip=markets_strip,
        hero_html=hero_html,
        side_html=side_html,
        grid_heading="The Latest",
        grid_html=grid_html,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    )


CATEGORY_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
{head}
</head>
<body>
  <div class="wrap topbar"><div>{today}</div></div>
  <div class="masthead"><a href="index.html">{site_name}</a></div>
  <nav class="catnav">
    {nav_links}
  </nav>
  <div class="wrap grid-section">
    <h2>{category_name}</h2>
    <div class="grid">
      {grid_html}
    </div>
  </div>
  <footer class="wrap">Generated {generated_at} UTC &nbsp;·&nbsp; This is a development spike, not a published site.</footer>
</body>
</html>
"""


def render_category_page(category: str, articles: list[dict]) -> str:
    grid_html = "\n".join(_article_html(a, "medium") for a in articles) or "<p>No stories yet.</p>"
    head = _head_html(
        title=f"{category.title()} — {SITE_NAME}",
        description=f"{category.title()} news from Palmer News, paired with live prediction-market context.",
        canonical_path=CATEGORY_PAGES[category],
    )
    return CATEGORY_TEMPLATE.format(
        head=head,
        today=datetime.now(timezone.utc).strftime("%A, %B %d, %Y").upper(),
        site_name=SITE_NAME,
        nav_links=_nav_html(active=category),
        category_name=category.title(),
        grid_html=grid_html,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    )


def write_category_page(category: str, articles: list[dict]) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / CATEGORY_PAGES[category]
    out_path.write_text(render_category_page(category, articles), encoding="utf-8")
    return out_path


PREDICTION_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
{head}
</head>
<body>
  <div class="wrap topbar"><div>{today}</div></div>
  <div class="masthead"><a href="index.html">{site_name}</a></div>
  <nav class="catnav">
    {nav_links}
  </nav>
  <div class="wrap grid-section">
    <h2>Prediction Markets</h2>
    <p style="color: var(--muted); font-size: 0.9rem;">Live odds from Polymarket, \
snapshotted at generation time.</p>
    <table class="pred-table">
      <thead><tr><th>Market</th><th>Odds</th><th>Volume</th></tr></thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>
  <footer class="wrap">Generated {generated_at} UTC &nbsp;·&nbsp; Source: Polymarket &nbsp;·&nbsp; This is a development spike, not a published site.</footer>
</body>
</html>
"""


def render_prediction_page(markets: list[dict]) -> str:
    rows = []
    for m in markets:
        title = html.escape(m["title"] or "")
        url = m.get("url") or "#"
        odds = ""
        if m.get("outcomes") and m.get("outcome_prices"):
            pairs = zip(m["outcomes"], m["outcome_prices"])
            odds = " · ".join(f"{html.escape(o)} {float(p) * 100:.0f}%" for o, p in pairs)
        vol = f"${m['volume']:,.0f}" if m.get("volume") else "—"
        rows.append(f'<tr><td><a href="{url}" target="_blank" rel="noopener">{title}</a></td>'
                     f'<td>{odds or "—"}</td><td>{vol}</td></tr>')
    head = _head_html(
        title=f"Prediction Markets — {SITE_NAME}",
        description="Live Polymarket prediction odds, tracked by Palmer News.",
        canonical_path=CATEGORY_PAGES["PREDICTION"],
    )
    return PREDICTION_TEMPLATE.format(
        head=head,
        today=datetime.now(timezone.utc).strftime("%A, %B %d, %Y").upper(),
        site_name=SITE_NAME,
        nav_links=_nav_html(active="PREDICTION"),
        rows="\n        ".join(rows) or "<tr><td colspan=3>No market data.</td></tr>",
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    )


def write_prediction_page(markets: list[dict]) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / CATEGORY_PAGES["PREDICTION"]
    out_path.write_text(render_prediction_page(markets), encoding="utf-8")
    return out_path


ARTICLE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
{head}
{jsonld}
</head>
<body>
  <div class="masthead" style="border-bottom: 2px solid var(--ink); padding: 1.6rem 0;">
    <a href="../index.html" style="font-size: 1.8rem;">{site_name}</a>
  </div>
  <div class="wrap" style="max-width: 720px;">
    <article style="padding: 2.2rem 0;">
      <div class="meta-line">{time_ago}</div>
      <h1 style="font-family: 'Playfair Display', serif; font-size: 2rem; line-height: 1.2; margin: 0 0 1rem;">{headline}</h1>
      {img}
      <div class="body">{body_html}</div>
      {widget}
      <a class="back" href="../index.html" style="display: inline-block; margin-top: 1.5rem; font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; color: var(--accent); text-decoration: none;">&larr; BACK TO FRONT PAGE</a>
      <div class="meta" style="font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; color: var(--muted); margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--rule);">Synthesized from {source_count} independent source(s): {sources} \
&nbsp;·&nbsp; Rewrite: Bedrock, grounded + verified &nbsp;·&nbsp; Not yet live.</div>
    </article>
  </div>
</body>
</html>
"""


def _jsonld_for_article(story: dict, headline: str, description: str, body: str) -> str:
    when = _iso_when(story)
    image = story.get("image_url") or ""
    # Minimal manual JSON escaping (avoids importing json just for this) —
    # these are LLM/RSS-derived strings, could contain quotes/backslashes.
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    return f"""<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "headline": "{esc(headline)}",
  "description": "{esc(description)}",
  "articleBody": "{esc(body)}",
  "datePublished": "{when}",
  "dateModified": "{when}",
  "image": "{esc(image)}",
  "publisher": {{"@type": "Organization", "name": "{SITE_NAME}"}},
  "author": {{"@type": "Organization", "name": "{SITE_NAME}"}}
}}
</script>"""


def render_article_page(story: dict, matched_market: dict | None) -> str:
    headline = html.escape(story.get("rewritten_title") or story["title"])
    dek = story.get("rewritten_summary") or story.get("rewritten") or story.get("description") or ""
    body = story.get("detail_body") or dek
    body_html = "".join(f"<p>{html.escape(p)}</p>" for p in body.split("\n\n") if p.strip())
    img = _img_html(story, "hero-img", 1600)
    widget = _market_widget_html(matched_market) if matched_market else ""
    sources = ", ".join(s.upper() for s in story.get("cluster_sources", [story.get("source", "unknown")]))

    head = _head_html(
        title=f"{story.get('rewritten_title') or story['title']} — {SITE_NAME}",
        description=dek[:200],
        canonical_path=f"articles/{story['slug']}.html",
        og_image=story.get("image_url"),
    )
    jsonld = _jsonld_for_article(story, story.get("rewritten_title") or story["title"], dek, body)

    return ARTICLE_TEMPLATE.format(
        head=head,
        jsonld=jsonld,
        site_name=SITE_NAME,
        time_ago=_time_ago(story),
        headline=headline,
        img=img,
        body_html=body_html,
        widget=widget,
        source_count=story.get("source_count", 1),
        sources=sources,
    )


def write_article_page(story: dict, matched_market: dict | None) -> Path:
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTICLES_DIR / f"{story['slug']}.html"
    out_path.write_text(render_article_page(story, matched_market), encoding="utf-8")
    return out_path


def write_page(html_out: str) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(html_out, encoding="utf-8")
    return OUTPUT_FILE


ROBOTS_TXT = """User-agent: *
Allow: /

# Explicitly welcoming AI/LLM crawlers — this site wants to be discoverable
# by generative-engine answers, not just traditional search.
User-agent: GPTBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: anthropic-ai
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Google-Extended
Allow: /

Sitemap: {base_url}/sitemap.xml
"""


def write_robots_txt() -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / "robots.txt"
    out_path.write_text(ROBOTS_TXT.format(base_url=BASE_URL), encoding="utf-8")
    return out_path


def write_sitemap(articles: list[dict]) -> Path:
    urls = [("", "index.html")] + [(f"", p) for p in CATEGORY_PAGES.values()]
    entries = []
    for _, path in urls:
        entries.append(f"  <url><loc>{BASE_URL}/{path}</loc></url>")
    for a in articles:
        if not a.get("slug"):
            continue
        lastmod = _iso_when(a) or datetime.now(timezone.utc).isoformat()
        entries.append(f'  <url><loc>{BASE_URL}/articles/{a["slug"]}.html</loc>'
                        f"<lastmod>{lastmod}</lastmod></url>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "\n".join(entries) + "\n</urlset>\n")
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / "sitemap.xml"
    out_path.write_text(xml, encoding="utf-8")
    return out_path


LLMS_TXT = """# {site_name}

> An automated news platform: AI-synthesized news coverage paired with live \
prediction-market odds, generated with no human editorial review.

Palmer News watches BBC, Guardian, and Al Jazeera RSS feeds, rewrites \
coverage under a strict grounding rule (only facts present in the source \
text, checked by a second independent verification pass), and attaches \
live Polymarket odds to stories where a genuine, LLM-confirmed match \
exists to a real prediction market. Content updates roughly every 30 \
minutes.

This is a development-stage project, not a fully live product. Content \
here is generated, not independently reported — treat it accordingly.

## Key pages
- [Homepage]({base_url}/index.html) — latest stories, prediction markets, top stories
- [Market]({base_url}/market.html) — world/political news
- [Finance]({base_url}/finance.html) — business/financial news
- [Technology]({base_url}/technology.html) — technology news
- [Prediction]({base_url}/prediction.html) — live Polymarket odds, standalone
"""


def write_llms_txt() -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / "llms.txt"
    out_path.write_text(LLMS_TXT.format(site_name=SITE_NAME, base_url=BASE_URL), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    print("build_site.py is a render module now. Run: python run_pipeline.py")
