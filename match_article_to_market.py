"""Per-article market matching — the harder half of Approach A (see design
doc, 'Category Taxonomy & Feature Split' / 'Next Steps'). Given one article
and the current Polymarket list, an LLM picks the correct matching market
(if any) or explicitly abstains, rather than a bare keyword/embedding
match. This is the disambiguate-by-date-and-criteria approach the design
doc settled on, not free keyword similarity.

Example this is built for: an Nvidia earnings article should match a
Polymarket market like "NVIDIA (NVDA) Q2 adjusted gross margin 72%-74%?" —
NOT just any market that happens to contain the word "Nvidia".
"""
from __future__ import annotations

import json
import re
from typing import Any

from bedrock_client import bedrock_complete

MATCH_PROMPT = """You are matching a news article to a prediction market, if \
one genuinely corresponds to it. Be conservative — abstain unless a market \
is clearly about the same real-world event/outcome as the article.

ARTICLE
Title: {title}
Description: {description}

CANDIDATE MARKETS (numbered)
{candidates}

Rules:
- A match means the market's outcome is a direct prediction about the same \
event/subject as the article — not just sharing a keyword (a market about \
"Nvidia stock price Dec 2026" does NOT match an article about an Nvidia \
product launch, for example).
- If multiple markets share a topic, prefer the one whose resolution \
criteria/date most specifically matches what the article describes.
- If no candidate is a genuine match, say so — do not force a weak match.

Respond with ONLY a JSON object, no other text:
{{"match_index": <int or null>, "reason": "<one short sentence>"}}"""


def _format_candidates(markets: list[dict[str, Any]]) -> str:
    lines = []
    for i, m in enumerate(markets):
        odds = ""
        if m.get("outcomes") and m.get("outcome_prices"):
            pairs = zip(m["outcomes"], m["outcome_prices"])
            odds = " / ".join(f"{o}: {float(p)*100:.0f}%" for o, p in pairs)
        end = m.get("end_date") or "no end date given"
        lines.append(f"{i}. {m['title']} (resolves: {end}) [{odds}]")
    return "\n".join(lines)


def _extract_json(text: str) -> dict | None:
    text = re.sub(r"```(?:json)?\s*|\s*```", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def match_article(article: dict[str, Any], markets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Returns the matched market dict (with a 'match_reason' key added),
    or None if no genuine match / on any failure. Never raises — a bad
    match here is worse than no match, so failures abstain."""
    if not markets:
        return None

    prompt = MATCH_PROMPT.format(
        title=article["title"],
        description=article.get("description") or article.get("rewritten") or "(none)",
        candidates=_format_candidates(markets),
    )
    try:
        raw = bedrock_complete(prompt, model="nemotron", max_tokens=150)
    except Exception as exc:  # noqa: BLE001
        print(f"[match] LLM call failed for '{article['title'][:60]}...': {exc}")
        return None

    parsed = _extract_json(raw)
    if not parsed or parsed.get("match_index") is None:
        return None

    idx = parsed["match_index"]
    if not isinstance(idx, int) or not (0 <= idx < len(markets)):
        print(f"[match] LLM returned out-of-range index {idx!r}, abstaining")
        return None

    matched = dict(markets[idx])
    matched["match_reason"] = parsed.get("reason", "")
    return matched


def match_articles(articles: list[dict[str, Any]], markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for a in articles:
        matched_market = match_article(a, markets)
        out.append({**a, "matched_market": matched_market})
    return out
