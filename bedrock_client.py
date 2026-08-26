"""Bedrock client wrapper supporting two model families used in this
pipeline:

- Anthropic Claude (via AnthropicBedrock, Messages API) — used earlier,
  kept as a fallback/comparison option.
- NVIDIA Nemotron (via boto3's Converse API, which Bedrock exposes as a
  unified interface across providers) — now the default, cheaper per the
  founder's request. Nemotron is a reasoning model: without suppressing
  it, it returns its chain-of-thought instead of a clean answer (confirmed
  2026-08-26). A `/no_think` system directive gets a direct, clean
  response — required for every prompt in this pipeline since they all
  expect parseable JSON, not a reasoning trace.
"""
from __future__ import annotations

import os

import boto3
from anthropic import AnthropicBedrock

REGION = os.getenv("AWS_REGION", "us-east-1")

# Friendly name -> (bedrock model/inference-profile id, family)
MODEL_MAP = {
    "nemotron": ("nvidia.nemotron-nano-9b-v2", "converse"),
    "haiku": ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "anthropic"),
    "sonnet": ("us.anthropic.claude-sonnet-5", "anthropic"),
}

DEFAULT_MODEL = "nemotron"

_anthropic_client: AnthropicBedrock | None = None
_bedrock_runtime = None


def _get_anthropic_client() -> AnthropicBedrock:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AnthropicBedrock(aws_region=REGION)
    return _anthropic_client


def _get_bedrock_runtime():
    global _bedrock_runtime
    if _bedrock_runtime is None:
        _bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)
    return _bedrock_runtime


def bedrock_complete(prompt: str, model: str = DEFAULT_MODEL, max_tokens: int = 1024) -> str:
    """One-shot text completion. Raises on failure — callers decide how to
    degrade (e.g. skip the story rather than publish something unground)."""
    model_id, family = MODEL_MAP[model]

    if family == "anthropic":
        client = _get_anthropic_client()
        resp = client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text

    # family == "converse" (Nemotron and any other non-Anthropic model)
    client = _get_bedrock_runtime()
    resp = client.converse(
        modelId=model_id,
        system=[{"text": "/no_think"}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens},
    )
    return resp["output"]["message"]["content"][0]["text"]
