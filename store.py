"""Persistent local state — SQLite, no server needed. Two jobs:

1. Article dedup/accumulation: without this, every run re-fetches whatever
   BBC/Guardian/etc happen to have live right now, reprocesses it with
   fresh (paid) LLM calls, and the site resets instead of growing. With
   it, only genuinely new articles get rewritten/verified/matched, and the
   site can be built from an accumulating pool.
2. Finance quote caching: Alpha Vantage's free tier has a low daily call
   cap — quotes are cached with a timestamp and only refreshed when stale.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent / "data" / "palmer_news.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    guid TEXT PRIMARY KEY,
    source TEXT,
    category TEXT,
    title TEXT,
    description TEXT,
    link TEXT,
    image_url TEXT,
    pub_date TEXT,
    rewritten_title TEXT,
    rewritten_summary TEXT,
    detail_body TEXT,
    slug TEXT,
    source_count INTEGER,
    verify_status TEXT,
    corroborated INTEGER,
    held_back INTEGER,
    hold_reason TEXT,
    matched_market_json TEXT,
    first_seen REAL
);

CREATE TABLE IF NOT EXISTS finance_quotes (
    symbol TEXT PRIMARY KEY,
    quote_json TEXT,
    fetched_at REAL
);

CREATE TABLE IF NOT EXISTS image_cache (
    query TEXT PRIMARY KEY,
    image_url TEXT,
    fetched_at REAL
);

CREATE TABLE IF NOT EXISTS market_cache (
    cache_key TEXT PRIMARY KEY,
    markets_json TEXT,
    fetched_at REAL
);

CREATE TABLE IF NOT EXISTS api_keys (
    api_key TEXT PRIMARY KEY,
    label TEXT,
    created_at REAL,
    active INTEGER DEFAULT 1,
    request_count INTEGER DEFAULT 0,
    last_used_at REAL
);

CREATE TABLE IF NOT EXISTS rate_limit_windows (
    api_key TEXT PRIMARY KEY,
    window_start REAL,
    count_in_window INTEGER
);
"""


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def existing_guids(conn: sqlite3.Connection) -> set[str]:
    return {row["guid"] for row in conn.execute("SELECT guid FROM articles")}


def save_article(conn: sqlite3.Connection, a: dict[str, Any]) -> None:
    a.setdefault("detail_body", None)
    a.setdefault("slug", None)
    a.setdefault("source_count", 1)
    conn.execute(
        """INSERT OR REPLACE INTO articles
        (guid, source, category, title, description, link, image_url, pub_date,
         rewritten_title, rewritten_summary, detail_body, slug, source_count,
         verify_status, corroborated, held_back, hold_reason,
         matched_market_json, first_seen)
        VALUES (:guid, :source, :category, :title, :description, :link,
                :image_url, :pub_date, :rewritten_title, :rewritten_summary,
                :detail_body, :slug, :source_count,
                :verify_status, :corroborated, :held_back, :hold_reason,
                :matched_market_json, :first_seen)""",
        a,
    )
    conn.commit()


def get_article_by_slug(conn: sqlite3.Connection, slug: str) -> dict | None:
    row = conn.execute("SELECT * FROM articles WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["matched_market"] = json.loads(d["matched_market_json"]) if d.get("matched_market_json") else None
    return d


def recent_articles(conn: sqlite3.Connection, limit: int = 40, exclude_held_back: bool = True,
                     category: str | None = None) -> list[dict]:
    query = "SELECT * FROM articles"
    where = []
    params: list = []
    if exclude_held_back:
        where.append("held_back = 0")
    if category:
        where.append("category = ?")
        params.append(category)
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY first_seen DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["matched_market"] = json.loads(d["matched_market_json"]) if d.get("matched_market_json") else None
        out.append(d)
    return out


def get_cached_quote(conn: sqlite3.Connection, symbol: str, max_age_s: int) -> dict | None:
    row = conn.execute("SELECT quote_json, fetched_at FROM finance_quotes WHERE symbol = ?", (symbol,)).fetchone()
    if not row:
        return None
    if time.time() - row["fetched_at"] > max_age_s:
        return None
    return json.loads(row["quote_json"])


def save_quote(conn: sqlite3.Connection, symbol: str, quote: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO finance_quotes (symbol, quote_json, fetched_at) VALUES (?, ?, ?)",
        (symbol, json.dumps(quote), time.time()),
    )
    conn.commit()


def get_cached_image(conn: sqlite3.Connection, query: str) -> str | None:
    # Stock-photo relevance for a fixed query doesn't go stale — cached
    # indefinitely, unlike the quote/market caches.
    row = conn.execute("SELECT image_url FROM image_cache WHERE query = ?", (query,)).fetchone()
    return row["image_url"] if row else None


def save_image(conn: sqlite3.Connection, query: str, image_url: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO image_cache (query, image_url, fetched_at) VALUES (?, ?, ?)",
        (query, image_url, time.time()),
    )
    conn.commit()


def get_cached_markets(conn: sqlite3.Connection, cache_key: str, max_age_s: int) -> list | None:
    row = conn.execute(
        "SELECT markets_json, fetched_at FROM market_cache WHERE cache_key = ?", (cache_key,)
    ).fetchone()
    if not row or time.time() - row["fetched_at"] > max_age_s:
        return None
    return json.loads(row["markets_json"])


def save_markets(conn: sqlite3.Connection, cache_key: str, markets: list) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO market_cache (cache_key, markets_json, fetched_at) VALUES (?, ?, ?)",
        (cache_key, json.dumps(markets), time.time()),
    )
    conn.commit()


def create_api_key(conn: sqlite3.Connection, key: str, label: str) -> None:
    conn.execute(
        "INSERT INTO api_keys (api_key, label, created_at, active, request_count) VALUES (?, ?, ?, 1, 0)",
        (key, label, time.time()),
    )
    conn.commit()


def validate_api_key(conn: sqlite3.Connection, key: str) -> bool:
    """Also records usage (request_count, last_used_at) as a side effect —
    every valid call is a use, not just a check."""
    row = conn.execute("SELECT active FROM api_keys WHERE api_key = ?", (key,)).fetchone()
    if not row or not row["active"]:
        return False
    conn.execute(
        "UPDATE api_keys SET request_count = request_count + 1, last_used_at = ? WHERE api_key = ?",
        (time.time(), key),
    )
    conn.commit()
    return True


def list_api_keys(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC")]


def revoke_api_key(conn: sqlite3.Connection, key: str) -> bool:
    cur = conn.execute("UPDATE api_keys SET active = 0 WHERE api_key = ?", (key,))
    conn.commit()
    return cur.rowcount > 0


def check_rate_limit(conn: sqlite3.Connection, key: str, limit_per_minute: int) -> tuple[bool, int, float]:
    """Fixed-window counter — simple, good enough at this scale (see the
    api_server.py load test: server handles 40-75 req/s aggregate before
    even single-process dev setup shows any strain; 60/min per key is
    generous headroom under that, not a number chosen to be stingy).

    Returns (allowed, remaining, seconds_until_reset)."""
    now = time.time()
    window_len = 60.0
    row = conn.execute(
        "SELECT window_start, count_in_window FROM rate_limit_windows WHERE api_key = ?", (key,)
    ).fetchone()

    if not row or now - row["window_start"] >= window_len:
        conn.execute(
            "INSERT OR REPLACE INTO rate_limit_windows (api_key, window_start, count_in_window) VALUES (?, ?, 1)",
            (key, now),
        )
        conn.commit()
        return True, limit_per_minute - 1, window_len

    remaining_time = window_len - (now - row["window_start"])
    if row["count_in_window"] >= limit_per_minute:
        return False, 0, remaining_time

    conn.execute(
        "UPDATE rate_limit_windows SET count_in_window = count_in_window + 1 WHERE api_key = ?", (key,)
    )
    conn.commit()
    return True, limit_per_minute - row["count_in_window"] - 1, remaining_time
