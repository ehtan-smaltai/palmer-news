"""Palmer News CLI — a thin client over the REST API (api_server.py), not a
separate code path. It calls the same endpoints any external integrator
would, so it exercises the real interface (including auth) rather than
reaching into the database directly like manage_keys.py does.

Headless-friendly: every read command supports --json for raw output
piped into jq/scripts; exit codes are 0 on success, 1 on any API/auth
error, 2 on bad usage — safe to use in cron jobs or other scripts.

Config precedence for API key/URL: --api-key/--api-url flag > PALMER_API_KEY/
PALMER_API_URL env var > saved config (~/.palmer_news/config.json).

Usage:
  palmer config set-key <key>
  palmer config set-url <url>          (default: http://localhost:8420)
  palmer articles [--category X] [--q TEXT] [--limit N] [--since ISO] [--json]
  palmer article <slug> [--json]
  palmer markets [--limit N] [--json]
  palmer categories [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# See run_pipeline.py for why — Windows console encoding can't represent
# most non-ASCII characters, routine now with global sports/entertainment
# article titles.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests

CONFIG_PATH = Path.home() / ".palmer_news" / "config.json"
DEFAULT_API_URL = "http://localhost:8420"


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def _resolve(args) -> tuple[str, str | None]:
    cfg = _load_config()
    api_url = args.api_url or os.getenv("PALMER_API_URL") or cfg.get("api_url") or DEFAULT_API_URL
    api_key = args.api_key or os.getenv("PALMER_API_KEY") or cfg.get("api_key")
    return api_url.rstrip("/"), api_key


def _request(args, path: str, params: dict | None = None) -> dict:
    api_url, api_key = _resolve(args)
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        resp = requests.get(f"{api_url}{path}", params=params or {}, headers=headers, timeout=15)
    except requests.exceptions.ConnectionError:
        print(f"error: couldn't reach {api_url} — is the API server running? "
              f"(python api_server.py)", file=sys.stderr)
        sys.exit(1)

    if resp.status_code == 401:
        print("error: missing or invalid API key. Set one with: palmer config set-key <key>",
              file=sys.stderr)
        sys.exit(1)
    if resp.status_code >= 400:
        print(f"error: {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)
    return resp.json()


def cmd_config(args) -> None:
    cfg = _load_config()
    if args.config_cmd == "set-key":
        cfg["api_key"] = args.value
        _save_config(cfg)
        print(f"Saved API key to {CONFIG_PATH}")
    elif args.config_cmd == "set-url":
        cfg["api_url"] = args.value
        _save_config(cfg)
        print(f"Saved API URL ({args.value}) to {CONFIG_PATH}")
    elif args.config_cmd == "show":
        api_url, api_key = _resolve(args)
        masked = (api_key[:6] + "..." + api_key[-4:]) if api_key else "(not set)"
        print(f"api_url = {api_url}")
        print(f"api_key = {masked}")


def cmd_articles(args) -> None:
    params = {"limit": args.limit, "offset": args.offset}
    if args.category:
        params["category"] = args.category
    if args.q:
        params["q"] = args.q
    if args.since:
        params["since"] = args.since

    data = _request(args, "/api/articles", params)
    if args.json:
        print(json.dumps(data, indent=2))
        return

    print(f"{data['count']} total, showing {len(data['articles'])}\n")
    for a in data["articles"]:
        market_tag = f" [PREDICTION: {a['matched_market']['title']}]" if a.get("matched_market") else ""
        print(f"[{a['category']}] {a['headline']}{market_tag}")
        if a.get("summary"):
            print(f"  {a['summary']}")
        print(f"  {a.get('published_at', '')}  slug={a['slug']}\n")


def cmd_article(args) -> None:
    data = _request(args, f"/api/articles/{args.slug}")
    if args.json:
        print(json.dumps(data, indent=2))
        return

    print(f"[{data['category']}] {data['headline']}\n")
    print(data.get("body") or data.get("summary") or "(no content)")
    if data.get("matched_market"):
        m = data["matched_market"]
        print(f"\nPREDICTION MARKET: {m['title']}")
        if m.get("outcomes") and m.get("outcome_prices"):
            for o, p in zip(m["outcomes"], m["outcome_prices"]):
                print(f"  {o}: {float(p) * 100:.0f}%")
    print(f"\npublished: {data.get('published_at', '')}  sources: {data.get('source_count', 1)}")


def cmd_markets(args) -> None:
    data = _request(args, "/api/markets", {"limit": args.limit})
    if args.json:
        print(json.dumps(data, indent=2))
        return

    print(f"{data['count']} markets (cached={data.get('cached')}, stale={data.get('stale')})\n")
    for m in data["markets"]:
        odds = ""
        if m.get("outcomes") and m.get("outcome_prices"):
            odds = " / ".join(f"{o}: {float(p) * 100:.0f}%" for o, p in zip(m["outcomes"], m["outcome_prices"]))
        print(f"- {m['title']}  [{odds}]")


def cmd_categories(args) -> None:
    data = _request(args, "/api/categories")
    if args.json:
        print(json.dumps(data, indent=2))
        return
    for c in data["categories"]:
        print(c)


def main() -> None:
    parser = argparse.ArgumentParser(prog="palmer", description="Palmer News CLI")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--api-url", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    p_config = sub.add_parser("config", help="Manage saved API key/URL")
    p_config.add_argument("config_cmd", choices=["set-key", "set-url", "show"])
    p_config.add_argument("value", nargs="?", default=None)
    p_config.set_defaults(func=cmd_config)

    p_articles = sub.add_parser("articles", help="List articles")
    p_articles.add_argument("--category", choices=["MARKET", "FINANCE", "TECHNOLOGY", "ENTERTAINMENT", "SPORTS"])
    p_articles.add_argument("--q", help="Keyword search")
    p_articles.add_argument("--limit", type=int, default=20)
    p_articles.add_argument("--offset", type=int, default=0)
    p_articles.add_argument("--since", help="ISO 8601 timestamp")
    p_articles.add_argument("--json", action="store_true")
    p_articles.set_defaults(func=cmd_articles)

    p_article = sub.add_parser("article", help="Get one article by slug")
    p_article.add_argument("slug")
    p_article.add_argument("--json", action="store_true")
    p_article.set_defaults(func=cmd_article)

    p_markets = sub.add_parser("markets", help="List prediction markets")
    p_markets.add_argument("--limit", type=int, default=40)
    p_markets.add_argument("--json", action="store_true")
    p_markets.set_defaults(func=cmd_markets)

    p_categories = sub.add_parser("categories", help="List categories")
    p_categories.add_argument("--json", action="store_true")
    p_categories.set_defaults(func=cmd_categories)

    args = parser.parse_args()
    if args.command != "config" and not (args.api_key or os.getenv("PALMER_API_KEY") or _load_config().get("api_key")):
        print("error: no API key configured. Run: palmer config set-key <key>", file=sys.stderr)
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
