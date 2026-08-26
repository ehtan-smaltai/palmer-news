"""Corroboration + clustering for the pipeline.

Two jobs:
1. Cluster articles from different outlets that are covering the same
   real-world event (cheap keyword-overlap, no LLM call per pair) — this
   is what lets detail pages synthesize across multiple independent
   sources instead of one outlet's thin teaser.
2. Gate volatile (breaking/violent/political-shock) stories: they need 2+
   independently-sourced cluster members before publishing; routine
   stories (Fed decisions, earnings, data releases) are fine single-source.
"""
from __future__ import annotations

import json
import re
from typing import Any

from bedrock_client import bedrock_complete

VOLATILE_KEYWORDS = {
    "killed", "dead", "death", "dies", "died", "attack", "attacked", "strike",
    "strikes", "war", "shooting", "shot", "bomb", "bombing", "assassinate",
    "assassination", "coup", "explosion", "hostage", "invasion", "missile",
    "airstrike", "massacre", "terror", "terrorist",
}

_STOPWORDS = {
    "the", "a", "an", "in", "on", "at", "to", "of", "for", "and", "or", "is",
    "was", "are", "were", "be", "as", "by", "with", "from", "after", "over",
    "amid", "into", "its", "it's", "his", "her", "their", "who", "what",
    "says", "said", "new", "us", "u.s", "will", "has", "have", "had",
}


_CAPITALIZED_STOPWORDS = {
    "the", "a", "an", "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday", "january", "february", "march", "april", "may",
    "june", "july", "august", "september", "october", "november", "december",
}


def _significant_words(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z']+", (text or "").lower())
    return {w for w in words if len(w) > 3 and w not in _STOPWORDS}


def _proper_nouns(text: str) -> set[str]:
    """Capitalized words NOT at the start of a sentence — a cheap proxy for
    named entities (people, places, organizations). Requiring at least one
    of these to overlap, on top of the generic word-overlap count, is what
    prevents two unrelated stories that happen to share boilerplate
    vocabulary from being merged into one story (confirmed bug 2026-08-26:
    a Haiti massacre, US-Iran sanctions, and a Prince Harry story got
    merged on generic overlap alone — merging is worse than not merging
    here, since it can let a single-sourced volatile story spuriously
    pass the corroboration gate via an unrelated second outlet)."""
    # Split into sentences, drop the first word of each (likely capitalized
    # regardless of whether it's a proper noun), then find capitalized words.
    sentences = re.split(r"(?<=[.!?])\s+", text or "")
    candidates = set()
    for sentence in sentences:
        words = sentence.split()
        for w in words[1:]:
            cleaned = re.sub(r"[^a-zA-Z]", "", w)
            if len(cleaned) > 2 and cleaned[0].isupper() and cleaned.lower() not in _CAPITALIZED_STOPWORDS:
                candidates.add(cleaned.lower())
    return candidates


def is_volatile(article: dict[str, Any]) -> bool:
    words = set(re.findall(r"[a-zA-Z]+", f"{article.get('title', '')} {article.get('description', '')}".lower()))
    return bool(words & VOLATILE_KEYWORDS)


def _same_story(a: dict[str, Any], b: dict[str, Any], min_shared: int) -> bool:
    """Deliberately conservative: generic word overlap alone isn't enough
    (see _proper_nouns docstring) — also require at least one shared
    proper noun (a name, place, or organization), or a much higher bar of
    generic overlap as a fallback for cases proper-noun extraction misses."""
    a_text = f"{a['title']} {a.get('description', '')}"
    b_text = f"{b['title']} {b.get('description', '')}"
    shared_words = len(_significant_words(a_text) & _significant_words(b_text))
    shared_entities = len(_proper_nouns(a_text) & _proper_nouns(b_text))

    if shared_words >= min_shared and shared_entities >= 1:
        return True
    return shared_words >= min_shared + 4  # very high generic overlap, no entity match needed


SAME_EVENT_PROMPT = """Do these news items describe the SAME specific \
real-world event — not just the same topic, organization, or region?

{items}

Two fines against the same company in two different countries are NOT the \
same event. Two articles about the same specific incident, decision, or \
announcement ARE the same event, even from different outlets.

Respond with ONLY a JSON object: {{"same_event": true}} or {{"same_event": false}}"""


def _llm_confirms_same_event(cluster: list[dict[str, Any]]) -> bool:
    """Heuristic word/entity overlap only produces CANDIDATES — this is the
    final check before actually merging them, since keyword overlap alone
    can't tell 'same event' from 'same topic' (confirmed bug: two separate
    TikTok fines in two different countries were flagged as candidates by
    the heuristic, which is correct — they DO share the entity 'TikTok' —
    but they are not the same event). On any failure, conservatively does
    NOT merge (under-clustering is the safe failure mode here)."""
    items = "\n\n".join(f"{i+1}. [{m['corro_source']}] {m['title']}: {m.get('description', '')}"
                         for i, m in enumerate(cluster))
    try:
        raw = bedrock_complete(SAME_EVENT_PROMPT.format(items=items), model="nemotron", max_tokens=100)
        text = re.sub(r"```(?:json)?\s*|\s*```", "", raw)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return False
        parsed = json.loads(match.group(0))
        return bool(parsed.get("same_event"))
    except Exception as exc:  # noqa: BLE001
        print(f"[cluster] same-event check failed, not merging: {exc}")
        return False


def cluster_articles(articles: list[dict[str, Any]], min_shared: int = 3) -> list[list[dict[str, Any]]]:
    """Greedy clustering: groups articles from DIFFERENT corro_sources that
    are judged the same real-world event (see _same_story) into one story
    cluster. This is what makes richer detail pages possible without
    scraping full article pages — a story corroborated by BBC + Guardian
    gives two independent descriptions of the same event to synthesize
    from, not just one outlet's teaser.

    Biased toward under-clustering, not over-clustering: failing to merge
    two articles about the same event just means a thinner detail page
    (safe). Merging two unrelated articles is worse — it can let a
    single-sourced volatile story spuriously pass the corroboration gate
    via an unrelated second outlet (this happened, see _proper_nouns)."""
    remaining = list(articles)
    clusters: list[list[dict[str, Any]]] = []

    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        still_remaining = []
        for other in remaining:
            if other["corro_source"] == seed["corro_source"]:
                still_remaining.append(other)
                continue
            if _same_story(seed, other, min_shared):
                cluster.append(other)
            else:
                still_remaining.append(other)
        remaining = still_remaining

        if len(cluster) > 1 and not _llm_confirms_same_event(cluster):
            # Heuristic found candidates but the LLM says they're not
            # actually the same event — fall back to treating each as its
            # own singleton cluster rather than merging incorrectly.
            clusters.extend([m] for m in cluster)
        else:
            clusters.append(cluster)

    return clusters


def evaluate_cluster(cluster: list[dict[str, Any]]) -> dict[str, Any]:
    """A cluster is corroborated if 2+ distinct outlets are in it. Volatile
    + single-source = held back."""
    distinct_sources = {m["corro_source"] for m in cluster}
    corroborated = len(distinct_sources) >= 2
    volatile = any(is_volatile(m) for m in cluster)
    held_back = volatile and not corroborated
    hold_reason = "volatile category, single-source only — held per corroboration gate" if held_back else None
    return {"corroborated": corroborated, "held_back": held_back, "hold_reason": hold_reason}
