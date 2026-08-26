"""Finance category: real stock quotes via Yahoo Finance's public chart
endpoint. Switched from Alpha Vantage 2026-08-26 — Alpha Vantage's free
tier hit its 25-request/day cap on the very first cold run and quotes
weren't meaningfully live anyway. Yahoo's endpoint has no such daily cap
and returns genuinely live intraday prices during market hours.

Caveat, stated plainly: this is an unofficial, undocumented public
endpoint (no API key, no ToS covering programmatic use) — widely relied on
by open-source finance tools, but Yahoo could change or block it without
notice. Worth knowing before depending on it for anything beyond an
experiment. If it ever breaks outright, the fallback is to drop the
Finance strip rather than resurrect Alpha Vantage's throttled quotes.
"""
from __future__ import annotations

import time
from typing import Any

import requests

from store import get_cached_quote, save_quote

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
WATCHLIST = ["AAPL", "NVDA", "MSFT", "TSLA", "SPY"]
CACHE_MAX_AGE_S = 120  # short cache — just to avoid hammering on rapid re-runs


def _fetch_quote(symbol: str) -> dict[str, Any] | None:
    try:
        resp = requests.get(
            CHART_URL.format(symbol=symbol),
            params={"interval": "1m", "range": "1d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        meta = resp.json()["chart"]["result"][0]["meta"]
        price = meta["regularMarketPrice"]
        prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
        change = price - prev_close if prev_close else 0.0
        change_pct = (change / prev_close * 100) if prev_close else 0.0
        return {
            "symbol": meta.get("symbol", symbol),
            "price": price,
            "change": change,
            "change_pct": f"{change_pct:.2f}",
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[finance] fetch failed for {symbol}: {exc}")
        return None


def fetch_finance_quotes(conn, watchlist: list[str] | None = None) -> list[dict[str, Any]]:
    quotes = []
    for symbol in watchlist or WATCHLIST:
        cached = get_cached_quote(conn, symbol, CACHE_MAX_AGE_S)
        if cached:
            quotes.append(cached)
            continue
        fresh = _fetch_quote(symbol)
        if fresh:
            save_quote(conn, symbol, fresh)
            quotes.append(fresh)
    return quotes


if __name__ == "__main__":
    from store import get_conn

    result = fetch_finance_quotes(get_conn())
    for q in result:
        print(f"  {q['symbol']}: {q['price']} ({q['change_pct']}%)")
