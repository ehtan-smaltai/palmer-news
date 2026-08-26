"""Pull currently open Kalshi markets.

Confirmed 2026-08-24 (via a throwaway Lambda in us-east-1): Kalshi's public
`/markets` listing works with NO authentication — it returns real market
data unauthenticated. The RSA-signed auth flow below is kept as a fallback
for if/when a specific endpoint (or a future Kalshi policy change) does
require it — try unauthenticated first, only sign if that comes back 401.

Also confirmed: this API is unreachable from at least one non-US network
(local dev machine, Malaysia ISP) but reachable from AWS us-east-1 — if
this keeps returning nothing when you run it locally, that's very likely
why. Run it from an AWS-hosted environment instead.
"""
from __future__ import annotations

import base64
import os
import time
from typing import Any

import requests

from lambda_relay import relay_get

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
MARKETS_PATH = "/markets"


def _load_private_key(path: str):
    from cryptography.hazmat.primitives import serialization

    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def _sign_request(private_key, timestamp_ms: str, method: str, path: str) -> str:
    """Kalshi's auth scheme: RSA-PSS(SHA256) over `timestamp+method+path`,
    base64-encoded. See Kalshi API docs > Authentication. Only needed as a
    fallback — public market listing works without it (see module docstring)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    message = f"{timestamp_ms}{method}{path}".encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def _signed_fetch(limit: int) -> list[dict[str, Any]] | None:
    """Fallback path — only used if the unauthenticated request 401s."""
    key_id = os.getenv("KALSHI_API_KEY_ID", "").strip()
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "").strip()
    if not key_id or not key_path:
        print("[kalshi] got 401 and no KALSHI_API_KEY_ID/KALSHI_PRIVATE_KEY_PATH "
              "set — register an API key at kalshi.com > Settings > API Keys")
        return None
    try:
        private_key = _load_private_key(key_path)
        timestamp_ms = str(int(time.time() * 1000))
        signature = _sign_request(private_key, timestamp_ms, "GET", MARKETS_PATH)
        headers = {
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        }
        resp = requests.get(
            f"{KALSHI_BASE_URL}{MARKETS_PATH}",
            headers=headers,
            params={"status": "open", "limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("markets", [])
    except Exception as exc:  # noqa: BLE001
        print(f"[kalshi] signed fetch also failed: {exc}")
        return None


def fetch_kalshi_markets(limit: int = 25) -> list[dict[str, Any]]:
    raw = None
    params = {"status": "open", "limit": limit}
    try:
        resp = requests.get(
            f"{KALSHI_BASE_URL}{MARKETS_PATH}",
            headers={"User-Agent": "news-spike/0.1"},
            params=params,
            timeout=8,
        )
        if resp.status_code == 401:
            raw = _signed_fetch(limit)
        else:
            resp.raise_for_status()
            raw = resp.json().get("markets", [])
    except Exception as exc:  # noqa: BLE001
        print(f"[kalshi] direct fetch failed ({exc}); trying relay")
        relay_result = relay_get(f"{KALSHI_BASE_URL}{MARKETS_PATH}", params=params)
        if relay_result.get("status") == 200 and "json" in relay_result:
            raw = relay_result["json"].get("markets", [])
        else:
            print(f"[kalshi] relay fetch also failed: {relay_result}; trying signed fallback")
            raw = _signed_fetch(limit)

    if raw is None:
        return []

    markets = []
    for m in raw:
        markets.append(
            {
                "source": "kalshi",
                "id": m.get("ticker"),
                "title": m.get("title"),
                "url": f"https://kalshi.com/markets/{m.get('event_ticker', '').lower()}",
                "category": m.get("category"),
                "yes_bid": m.get("yes_bid"),
                "yes_ask": m.get("yes_ask"),
                "volume": m.get("volume"),
                "end_date": m.get("close_time"),
            }
        )
    return markets


if __name__ == "__main__":
    result = fetch_kalshi_markets(limit=10)
    print(f"Fetched {len(result)} Kalshi markets")
    for m in result[:5]:
        print(f"  - {m['title']} (yes_bid={m['yes_bid']})")
