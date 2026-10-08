"""AWS Lambda entry point for the tool services.

Every tool is deployed as its own function from this one handler; the ``TOOL`` environment
variable says which tool a function serves, and its IAM role only reaches that tool's data
(``access.py``). API Gateway (HTTP API, payload v2) calls ``POST /tools/{tool}`` with the tool
arguments as a JSON body.
"""

from __future__ import annotations

import base64
import inspect
import json
import os
import time

from ..tools_impl import TOOL_NAMES

_backend = None  # reused across warm invocations


def _get_backend():
    global _backend
    if _backend is None:
        from .dynamo import DynamoBackend

        _backend = DynamoBackend()
    return _backend


def handler(event: dict, context) -> dict:
    tool = os.environ["TOOL"]
    start = time.perf_counter()
    status, body = _invoke(tool, event)
    # One structured line per call; CloudWatch Logs Insights can query it by field.
    print(
        json.dumps(
            {
                "tool": tool,
                "status": status,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                "request_id": getattr(context, "aws_request_id", None),
            }
        )
    )
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def _invoke(tool: str, event: dict) -> tuple[int, dict]:
    if tool not in TOOL_NAMES:
        return 500, {"error": f"Misconfigured function: unknown tool {tool!r}"}
    try:
        args = _body(event)
    except ValueError as e:
        return 400, {"error": str(e)}
    fn = getattr(_get_backend(), tool)
    params = inspect.signature(fn).parameters
    if unknown := set(args) - set(params):
        return 400, {"error": f"Unknown argument(s) for {tool}: {sorted(unknown)}"}
    try:
        return 200, fn(**args)
    except TypeError as e:  # missing required argument
        return 400, {"error": str(e)}


def _body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        args = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Body is not valid JSON: {e}") from None
    if not isinstance(args, dict):
        raise ValueError("Body must be a JSON object of tool arguments.")
    return args
