"""Pull currently open Polymarket markets from the public Gamma API.

No auth required for read-only market listings. Returns a normalized list
of dicts so build_prediction_page.py doesn't need to know Polymarket's
specific response shape.

Network note (confirmed 2026-08-24): this API is unreachable from at least
this dev machine's network (TCP-level timeout). Tries a direct request
first (works fine once this runs on AWS for real); falls back to the
`news-fetch-relay` Lambda (see lambda_relay.py) if the direct call fails,
so it also works from a blocked local network in the meantime.
"""
from __future__ import annotations

import json
from typing import Any

import requests

from lambda_relay import relay_get

GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"


def fetch_polymarket_markets(limit: int = 25) -> list[dict[str, Any]]:
    """Fetch the top `limit` open markets by volume.

    Degrades gracefully: on any network/parse error (direct AND relay),
    returns an empty list with the error printed, rather than raising and
    killing the whole page build (Kalshi or the rest of the page should
    still render).
    """
    params = {
        "active": "true",
        "closed": "false",
        "limit": limit,
        "order": "volume",
        "ascending": "false",
    }
    raw = None
    try:
        # Short timeout deliberately — on networks where direct access is
        # blocked (confirmed for at least this dev machine), this fails
        # fast so the relay fallback kicks in quickly instead of adding
        # multiple seconds of dead wait on every cache-miss request.
        resp = requests.get(GAMMA_MARKETS_URL, params=params, timeout=3)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as exc:  # noqa: BLE001 - intentional broad catch, see docstring
        print(f"[polymarket] direct fetch failed ({exc}); trying relay")
        relay_result = relay_get(GAMMA_MARKETS_URL, params=params)
        if relay_result.get("status") == 200 and "json" in relay_result:
            raw = relay_result["json"]
        else:
            print(f"[polymarket] relay fetch also failed: {relay_result}")
            return []

    if raw is None:
        return []

    markets = []
    for m in raw:
        try:
            outcomes = json.loads(m.get("outcomes", "[]"))
            outcome_prices = json.loads(m.get("outcomePrices", "[]"))
        except (json.JSONDecodeError, TypeError):
            outcomes, outcome_prices = [], []

        markets.append(
            {
                "source": "polymarket",
                "id": m.get("id"),
                "title": m.get("question") or m.get("title"),
                "slug": m.get("slug"),
                "url": f"https://polymarket.com/event/{m.get('slug')}" if m.get("slug") else None,
                "category": m.get("category") or m.get("groupItemTitle"),
                "outcomes": outcomes,
                "outcome_prices": outcome_prices,
                "volume": _safe_float(m.get("volume")),
                "liquidity": _safe_float(m.get("liquidity")),
                "end_date": m.get("endDate"),
            }
        )
    return markets


def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    result = fetch_polymarket_markets(limit=10)
    print(f"Fetched {len(result)} Polymarket markets")
    for m in result[:5]:
        print(f"  - {m['title']} ({m['outcomes']} @ {m['outcome_prices']})")
