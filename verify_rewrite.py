"""The verify pass from the design doc's grounding rule: a second, separate
LLM call checks whether the rewrite actually stayed inside the source text,
rather than trusting the rewrite prompt's instructions alone to prevent
hallucination. Single-pass instruction-following reduces hallucination;
it doesn't reliably prevent it — this catches what slips through.
"""
from __future__ import annotations

import json
import re

from bedrock_client import bedrock_complete

VERIFY_PROMPT = """You are fact-checking a rewritten news summary against its \
source text. Be strict — this is a hallucination check, not a quality review.

SOURCE (the only text the rewrite is allowed to draw from):
{source}

REWRITE (headline + summary to check):
{rewrite}

List every claim, name, number, or detail in the REWRITE that is NOT \
literally stated or directly implied by the SOURCE. Minor rephrasing is \
fine; invented specifics are not.

Respond with ONLY a JSON object, no other text:
{{"ok": true}} if every claim in the rewrite is supported, or
{{"ok": false, "unsupported": ["<claim 1>", "<claim 2>", ...]}} if not."""


def _extract_json(text: str) -> dict | None:
    # Strip markdown code fences (```json ... ``` or ``` ... ```) — models
    # sometimes wrap JSON in them despite being told not to.
    text = re.sub(r"```(?:json)?\s*|\s*```", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def verify_rewrite(source_title: str, source_description: str, rewritten_title: str, rewritten_summary: str) -> dict:
    """Returns {"ok": bool, "unsupported": [...], "checked": bool}.
    `checked=False` means the verify call itself failed (network/parse
    error) — callers should treat that as 'not verified' and be
    conservative, not as a pass."""
    prompt = VERIFY_PROMPT.format(
        source=f"Title: {source_title}\nDescription: {source_description}",
        rewrite=f"Headline: {rewritten_title}\nSummary: {rewritten_summary}",
    )
    try:
        raw = bedrock_complete(prompt, model="nemotron", max_tokens=600)
        parsed = _extract_json(raw)
        if not parsed:
            print("[verify] could not parse verifier response")
            return {"ok": False, "unsupported": [], "checked": False}
        return {"ok": bool(parsed.get("ok")), "unsupported": parsed.get("unsupported", []), "checked": True}
    except Exception as exc:  # noqa: BLE001
        print(f"[verify] verifier call failed: {exc}")
        return {"ok": False, "unsupported": [], "checked": False}
