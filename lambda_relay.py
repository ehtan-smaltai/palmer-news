"""Thin client for the `news-fetch-relay` Lambda function (us-east-1).

Why this exists: Polymarket's API is unreachable from at least this dev
machine's network (confirmed 2026-08-24 — TCP-level timeout, not an HTTP
error), but reachable fine from AWS. Rather than requiring every dev
machine to be on a US network, HTTP fetches route through this persistent
Lambda relay, which does the actual outbound call from inside AWS and
returns the result over the (unblocked) AWS API path.

Auth: uses the ambient AWS credential chain (the local `aws configure`
default profile on this machine). No API Gateway, no public endpoint —
only whoever can authenticate as this AWS account can invoke it.
"""
from __future__ import annotations

import json
import os
from typing import Any

import boto3

FUNCTION_NAME = "news-fetch-relay"
REGION = os.getenv("AWS_REGION", "us-east-1")

_client = None


def _lambda_client():
    global _client
    if _client is None:
        _client = boto3.client("lambda", region_name=REGION)
    return _client


def relay_get(url: str, params: dict | None = None, headers: dict | None = None) -> dict[str, Any]:
    """Fetch `url` from inside AWS via the relay Lambda. Returns the same
    shape the relay produces: {"status": int, "json": ...} or
    {"status": int, "text": ...} or {"status": None, "error": "..."}.

    Raises nothing on network/relay failure — callers already handle a
    missing/empty result gracefully (see fetch_polymarket.py / fetch_kalshi.py).
    """
    payload = {"url": url, "params": params or {}, "headers": headers or {}}
    try:
        resp = _lambda_client().invoke(
            FunctionName=FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )
        body = json.loads(resp["Payload"].read())
        return body
    except Exception as exc:  # noqa: BLE001
        print(f"[lambda_relay] invoke failed: {exc}")
        return {"status": None, "error": str(exc)}
