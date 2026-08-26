"""Rewrite fetched articles under the grounding rule from the design doc:
never state a claim/name/number/detail that isn't literally present in the
source text. Note the source text here is the RSS title+description (a
short teaser), NOT the full article body — same caveat flagged for
Bloomberg earlier applies to BBC/CNN's RSS descriptions too. The rewrite
is deliberately short and thin as a result; that's correct behavior, not a
bug — a longer, more detailed "rewrite" of a 2-sentence teaser would mean
the model invented the extra detail.

This is a single-pass rewrite only (no verify pass yet) — the two-pass
grounding+verify architecture from the design doc's Constraints section is
NOT implemented here. This is UI-scaffolding scope; treat rewritten output
as unverified until that pass exists.
"""
from __future__ import annotations

import json
import re
from typing import Any

from bedrock_client import bedrock_complete
from verify_rewrite import verify_rewrite

GROUNDING_PROMPT = """You are rewriting a news item for a neutral news platform, \
in your own words — not the original outlet's headline or phrasing.

Source title: {title}
Source description (this is a short teaser from an RSS feed, not the full \
article): {description}

Rules:
- Only state facts, names, numbers, and details that are literally present \
in the source title/description above.
- Do NOT infer, guess, or fill in anything not stated, even if it seems \
obvious from context.
- Do NOT use outside knowledge about this event.
- Write a genuinely different headline from the source title — same facts, \
your own wording and structure, not a trivial synonym swap.
- If the source text is too thin to say much, write a short, honest \
summary rather than padding it out.
- Neutral tone. No editorializing, no adjectives implying judgment.
- Summary: 2-3 sentences maximum.

Respond with ONLY a JSON object, no other text:
{{"headline": "<your rewritten headline>", "summary": "<your rewritten summary>"}}"""


def _extract_json(text: str) -> dict | None:
    text = re.sub(r"```(?:json)?\s*|\s*```", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def rewrite_article(article: dict[str, Any]) -> dict[str, Any]:
    prompt = GROUNDING_PROMPT.format(
        title=article["title"],
        description=article["description"] or "(no description provided)",
    )
    rewritten_title = None
    rewritten = None
    verify_status = "not_attempted"
    try:
        raw = bedrock_complete(prompt, model="nemotron", max_tokens=250)
        parsed = _extract_json(raw)
        if parsed:
            rewritten_title = (parsed.get("headline") or "").strip() or None
            rewritten = (parsed.get("summary") or "").strip() or None
        else:
            print(f"[rewrite] could not parse JSON for '{article['title'][:60]}...'")
    except Exception as exc:  # noqa: BLE001
        print(f"[rewrite] failed for '{article['title'][:60]}...': {exc}")

    if rewritten_title and rewritten:
        result = verify_rewrite(article["title"], article["description"], rewritten_title, rewritten)
        if result["ok"]:
            verify_status = "passed"
        else:
            verify_status = "failed" if result["checked"] else "unchecked"
            print(f"[verify] rewrite for '{article['title'][:60]}...' "
                  f"{'failed' if result['checked'] else 'could not be checked'} "
                  f"— falling back to raw description. Unsupported: {result['unsupported']}")
            # Fall back to un-rewritten (but still grounded — it's literally
            # the source's own teaser) text rather than publish an unverified
            # or failed rewrite. Headline still gets a light pass-through.
            rewritten_title = None
            rewritten = None

    return {
        **article,
        "rewritten_title": rewritten_title,
        "rewritten": rewritten,
        "verify_status": verify_status,
    }


def rewrite_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [rewrite_article(a) for a in articles]


if __name__ == "__main__":
    from fetch_news import fetch_news

    articles = fetch_news(limit_per_feed=3)
    rewritten = rewrite_articles(articles)
    for a in rewritten:
        print(f"\n[{a['source']}] {a['title']}")
        print(f"  -> {a['rewritten']}")
