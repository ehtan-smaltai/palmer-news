# Palmer News

An automated news platform: AI-synthesized news coverage paired with live
prediction-market odds and (planned) social signal — three independent,
hard-to-manipulate signals instead of one editorial voice claiming to be
neutral.

- **News** — what's happening, synthesized from BBC/Guardian/Al Jazeera RSS
- **Prediction markets** — where the money is, via live Polymarket odds
- **Social listening** — what people are saying (not yet built)

**Status: development-stage experiment.** This runs with no human editorial
review — content is entirely AI-generated. Treat it accordingly. See
`docs/DESIGN.md`-equivalent notes inline in the source for the reasoning
behind each safety mechanism.

## How it works

1. **Fetch** — pulls recent articles from BBC, Guardian, and Al Jazeera RSS
   feeds (`fetch_news.py`), plus live Polymarket market data
   (`fetch_polymarket.py`).
2. **Cluster** — groups articles from different outlets covering the same
   real-world event (`corroboration.py`), using keyword/entity overlap plus
   an LLM confirmation pass to avoid false merges.
3. **Corroboration gate** — volatile stories (breaking/violent/political-
   shock) need 2+ independent sources before publishing; routine stories
   are fine single-source.
4. **Rewrite + verify** — Bedrock (NVIDIA Nemotron) rewrites each story
   under a strict grounding rule (only facts present in the source text),
   then a second, independent LLM call verifies the rewrite didn't
   introduce unsupported claims. Failures fall back to safe, short text
   instead of publishing (`detail_article.py`, `verify_rewrite.py`).
5. **Match** — an LLM conservatively matches articles to a genuinely
   corresponding Polymarket market, abstaining rather than forcing a weak
   match (`match_article_to_market.py`).
6. **Persist + render** — everything lands in SQLite (`store.py`) so runs
   accumulate instead of resetting, then renders both a human-facing static
   site (`build_site.py`) and a JSON API (`api_server.py`) — **the API is
   the primary interface**; the HTML site is a secondary, human-facing view
   of the same data.

`run_pipeline.py` ties all of the above together and is the real
entrypoint; `scheduler_loop.py` runs it on a 30-minute loop.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your own AWS/Bedrock, Pexels, Alpha Vantage keys
python run_pipeline.py       # one pipeline run — fetch, process, render
python api_server.py         # serves the JSON API on http://localhost:8420
```

Open `output/index.html` directly in a browser for the human-facing site,
or hit `http://localhost:8420/docs` for the interactive API schema.

### API keys

All `/api/*` endpoints require a key in the `X-API-Key` header (`/`, `/docs`,
and `/openapi.json` stay open so you can read the schema first).

```bash
python manage_keys.py create "your app name"   # prints a new key, shown once
python manage_keys.py list                     # usage per key (masked)
python manage_keys.py revoke <key>              # deactivate a key
```

### CLI

`palmer_cli.py` is a thin client over the same REST API — headless-friendly,
`--json` on every read command for piping into scripts/`jq`, exit code 1 on
any API/auth error.

```bash
python palmer_cli.py config set-key <key>
python palmer_cli.py articles --category MARKET --q "Iran" --limit 10
python palmer_cli.py article <slug>
python palmer_cli.py markets --limit 20
python palmer_cli.py categories
```

## Architecture notes worth knowing before touching this

- **Network**: Polymarket's API is unreachable from some networks (confirmed
  TCP-level block from at least one non-US ISP). `lambda_relay.py` +
  `fetch_polymarket.py` fall back to a small AWS Lambda relay when direct
  access fails — see the module docstrings.
- **No source impersonation, no full-article scraping (yet)**: rewrites are
  grounded only in RSS teaser text, not scraped full articles — a
  deliberate choice to keep legal/ToS exposure low. See `rewrite_news.py`
  and `detail_article.py` docstrings.
- **No outbound links to source outlets**: news cards host the full read on
  this platform; the Polymarket link on matched-market widgets is a
  separate, deliberate exception.
- **Model choice**: NVIDIA Nemotron (via Bedrock) is used throughout for
  cost — it hallucinates meaningfully more than Claude on longer generation
  tasks (confirmed, documented in `detail_article.py`), which is an
  accepted tradeoff; the verify pass exists specifically to catch this.

## License

MIT — see [LICENSE](LICENSE).
