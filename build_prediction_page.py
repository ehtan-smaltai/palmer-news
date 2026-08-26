"""Build the Prediction section: pull live Polymarket + Kalshi markets and
render a static local HTML page. No LLM involved — this is the trivial,
near-zero-risk half of the platform (see design doc, 'Category Taxonomy &
Feature Split'). Odds are fetched at generation time, not polled live.

Usage: python build_prediction_page.py
Output: output/prediction.html
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from fetch_polymarket import fetch_polymarket_markets

# Kalshi fetcher (fetch_kalshi.py) still works and is left in place, but is
# not called here for now — sticking to Polymarket only per current scope.
# Re-add `from fetch_kalshi import fetch_kalshi_markets` + the call below
# to bring it back.

load_dotenv()

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_FILE = OUTPUT_DIR / "prediction.html"


def _format_polymarket_row(m: dict) -> str:
    odds = ""
    if m["outcomes"] and m["outcome_prices"]:
        pairs = zip(m["outcomes"], m["outcome_prices"])
        odds = " · ".join(f"{o}: {float(p) * 100:.0f}%" for o, p in pairs)
    title = html.escape(m["title"] or "(untitled)")
    url = m["url"] or "#"
    category = html.escape(m["category"] or "—")
    vol = f"${m['volume']:,.0f}" if m["volume"] else "—"
    return f"""
    <tr>
      <td><a href="{url}" target="_blank" rel="noopener">{title}</a></td>
      <td>{category}</td>
      <td>{html.escape(odds) or "—"}</td>
      <td>{vol}</td>
    </tr>"""


def _format_kalshi_row(m: dict) -> str:
    title = html.escape(m["title"] or "(untitled)")
    url = m["url"] or "#"
    category = html.escape(m["category"] or "—")
    odds = "—"
    if m.get("yes_bid") is not None:
        odds = f"YES: {m['yes_bid']}¢"
    vol = f"{m['volume']:,}" if m.get("volume") else "—"
    return f"""
    <tr>
      <td><a href="{url}" target="_blank" rel="noopener">{title}</a></td>
      <td>{category}</td>
      <td>{odds}</td>
      <td>{vol}</td>
    </tr>"""


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Prediction — spike output</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; max-width: 900px;
         margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 0.25rem; }}
  .meta {{ color: #666; font-size: 0.85rem; margin-bottom: 2rem; }}
  h2 {{ font-size: 1.1rem; border-bottom: 1px solid #ddd; padding-bottom: 0.4rem;
        margin-top: 2.5rem; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 0.75rem; }}
  th {{ text-align: left; font-size: 0.75rem; text-transform: uppercase;
        color: #888; padding: 0.4rem 0.5rem; border-bottom: 1px solid #ddd; }}
  td {{ padding: 0.5rem; border-bottom: 1px solid #eee; font-size: 0.9rem; }}
  a {{ color: #1a56db; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .empty {{ color: #888; font-style: italic; padding: 1rem 0; }}
</style>
</head>
<body>
  <h1>Prediction section — spike output</h1>
  <div class="meta">Generated {generated_at} UTC. Odds are a snapshot at
    generation time, not live-polled.</div>

  <h2>Polymarket ({poly_count} markets)</h2>
  {poly_table}
</body>
</html>
"""


def build() -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)

    poly_markets = fetch_polymarket_markets(limit=25)

    poly_rows = "\n".join(_format_polymarket_row(m) for m in poly_markets)
    poly_table = (
        f'<table><thead><tr><th>Market</th><th>Category</th><th>Odds</th>'
        f'<th>Volume</th></tr></thead><tbody>{poly_rows}</tbody></table>'
        if poly_markets
        else '<div class="empty">No Polymarket data — fetch failed, see console.</div>'
    )

    html_out = PAGE_TEMPLATE.format(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        poly_count=len(poly_markets),
        poly_table=poly_table,
    )

    OUTPUT_FILE.write_text(html_out, encoding="utf-8")
    print(f"Wrote {OUTPUT_FILE} ({len(poly_markets)} Polymarket)")
    return OUTPUT_FILE


if __name__ == "__main__":
    build()
