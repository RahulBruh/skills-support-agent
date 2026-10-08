"""Client for the deployed tool services (API Gateway + one Lambda per tool).

Requests are signed with SigV4 using the caller's AWS credentials; the API's routes use the IAM
authorizer, so only principals with ``execute-api:Invoke`` (e.g. the stack's client policy) can
call the tools.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class ApiBackend:
    """Same tool methods as ``Backend``, served remotely. Set ``$SUPPORT_AGENT_API_URL``."""

    def __init__(self, url: str | None = None, region: str | None = None, *, session=None):
        import boto3

        self.url = (url or os.environ.get("SUPPORT_AGENT_API_URL") or "").rstrip("/")
        if not self.url:
            raise RuntimeError(
                "Set SUPPORT_AGENT_API_URL to the stack's ApiUrl output (see infra/README.md)."
            )
        self.session = session or boto3.Session()
        self.region = region or self.session.region_name or _region_from_url(self.url)

    def _call(self, tool: str, **args) -> dict:
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest

        body = json.dumps({k: v for k, v in args.items() if v is not None})
        req = AWSRequest(
            method="POST",
            url=f"{self.url}/tools/{tool}",
            data=body,
            headers={"content-type": "application/json"},
        )
        creds = self.session.get_credentials().get_frozen_credentials()
        SigV4Auth(creds, "execute-api", self.region).add_auth(req)
        http_req = urllib.request.Request(
            req.url, data=body.encode(), headers=dict(req.headers), method="POST"
        )
        try:
            with urllib.request.urlopen(http_req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            # Surface the failure to the model as a tool result rather than crashing the run.
            return {"error": f"{tool} failed with HTTP {e.code}", "detail": detail}

    def lookup_ticket(self, ticket_id: str | None = None, account: str | None = None) -> dict:
        return self._call("lookup_ticket", ticket_id=ticket_id, account=account)

    def get_account_status(self, account: str) -> dict:
        return self._call("get_account_status", account=account)

    def get_purchase_history(self, account: str) -> dict:
        return self._call("get_purchase_history", account=account)

    def search_kb(self, query: str, top_k: int = 3) -> dict:
        return self._call("search_kb", query=query, top_k=top_k)

    def get_service_status(self, game: str | None = None) -> dict:
        return self._call("get_service_status", game=game)


def _region_from_url(url: str) -> str:
    # https://<id>.execute-api.<region>.amazonaws.com
    host = url.split("://", 1)[-1].split("/", 1)[0]
    parts = host.split(".")
    return parts[2] if len(parts) > 3 and parts[1] == "execute-api" else "us-east-1"
