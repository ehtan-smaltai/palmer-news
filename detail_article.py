"""Generates the longer detail-page article for a story cluster (see
corroboration.cluster_articles). Grounded on the COMBINED text of every
cluster member — for a 2-3 outlet corroborated story, that's genuinely
more raw material than any single RSS teaser, without scraping full
article pages. Same grounding rule as the homepage rewrite; same verify
pass, run against the longer body since it has more room to drift.

Honest limitation: single-source stories only have one outlet's teaser to
draw from, so their detail page is necessarily thinner — this is real
depth, not padding, so a single-source story just gets a short page. That
was a deliberate choice over generating "detail" from nothing.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from bedrock_client import bedrock_complete
from verify_rewrite import verify_rewrite

DETAIL_PROMPT = """You are writing a detailed article for a neutral news \
platform, in your own words — not copying any source's phrasing.

SOURCE MATERIAL (one or more independent outlets' coverage of the same \
event — this is the ONLY material you may draw from):
{combined_source}

Rules:
- Only include facts, names, numbers, and details literally present in the \
source material above. Do not infer, guess, or use outside knowledge.
- If multiple outlets are given, synthesize across them — you may include \
a detail that appears in only one outlet, but do not treat outlets as \
disagreeing unless they actually state different things.
- Write a genuinely different headline from any source outlet's original \
title.
- Write a full article body: several paragraphs if the source material \
supports it, but do NOT pad — if the material is thin, a short, honest \
article is correct, not a stretched one.
- Neutral tone, no editorializing.

Respond with ONLY a JSON object, no other text:
{{"headline": "<headline>", "summary": "<1-2 sentence dek for the homepage \
card>", "body": "<the full article body, paragraphs separated by \\n\\n>"}}"""


def _extract_json(text: str) -> dict | None:
    text = re.sub(r"```(?:json)?\s*|\s*```", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def make_slug(guid: str) -> str:
    return hashlib.sha256(guid.encode("utf-8")).hexdigest()[:16]


def select_primary(cluster: list[dict[str, Any]]) -> dict[str, Any]:
    """The cluster member with the richest teaser becomes the identity
    (guid/image/category) for the resulting story. Exposed separately so
    run_pipeline.py can compute the same primary guid for dedup checks
    without re-deriving the logic."""
    return max(cluster, key=lambda a: len(a.get("description") or ""))


def _combined_source_text(cluster: list[dict[str, Any]]) -> str:
    parts = []
    for m in cluster:
        parts.append(f"[{m['corro_source'].upper()}] {m['title']}\n{m.get('description', '')}")
    return "\n\n".join(parts)


def build_detail_article(cluster: list[dict[str, Any]]) -> dict[str, Any]:
    """Returns the primary article's dict (richest teaser in the cluster,
    used for image/category/guid/link identity) augmented with
    rewritten_title, rewritten (dek), detail_body, verify_status, slug,
    and source_count."""
    primary = select_primary(cluster)
    combined_source = _combined_source_text(cluster)

    prompt = DETAIL_PROMPT.format(combined_source=combined_source)
    rewritten_title = rewritten_summary = detail_body = None
    verify_status = "not_attempted"

    try:
        raw = bedrock_complete(prompt, model="nemotron", max_tokens=1200)
        parsed = _extract_json(raw)
        if parsed:
            rewritten_title = (parsed.get("headline") or "").strip() or None
            rewritten_summary = (parsed.get("summary") or "").strip() or None
            detail_body = (parsed.get("body") or "").strip() or None
        else:
            print(f"[detail] could not parse JSON for cluster seeded by '{primary['title'][:60]}...'")
    except Exception as exc:  # noqa: BLE001
        print(f"[detail] generation failed for cluster seeded by '{primary['title'][:60]}...': {exc}")

    if rewritten_title and detail_body:
        result = verify_rewrite(
            source_title="(multi-source, see below)",
            source_description=combined_source,
            rewritten_title=rewritten_title,
            rewritten_summary=f"{rewritten_summary}\n\n{detail_body}",
        )
        if result["ok"]:
            verify_status = "passed"
        else:
            verify_status = "failed" if result["checked"] else "unchecked"
            print(f"[detail] verify {'failed' if result['checked'] else 'could not check'} for "
                  f"'{primary['title'][:60]}...' — falling back to short/unrewritten. "
                  f"Unsupported: {result['unsupported']}")
            rewritten_title = None
            rewritten_summary = None
            detail_body = None

    return {
        **primary,
        "rewritten_title": rewritten_title,
        "rewritten": rewritten_summary,
        "detail_body": detail_body,
        "verify_status": verify_status,
        "slug": make_slug(primary["guid"]),
        "source_count": len({m["corro_source"] for m in cluster}),
        "cluster_sources": sorted({m["corro_source"] for m in cluster}),
    }
