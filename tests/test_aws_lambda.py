"""The Lambda handler and the SigV4 API client, without AWS."""

import base64
import io
import json

import pytest

from support_agent.tools_impl import JsonBackend

pytest.importorskip("boto3")

from support_agent.aws import lambdas  # noqa: E402
from support_agent.aws.http import ApiBackend, _region_from_url  # noqa: E402


@pytest.fixture
def handler(monkeypatch, dynamo):
    monkeypatch.setattr(lambdas, "_backend", dynamo)

    def call(tool: str, body, *, b64: bool = False):
        monkeypatch.setenv("TOOL", tool)
        raw = body if isinstance(body, str) else json.dumps(body)
        event = {"body": base64.b64encode(raw.encode()).decode() if b64 else raw}
        if b64:
            event["isBase64Encoded"] = True
        res = lambdas.handler(event, None)
        return res["statusCode"], json.loads(res["body"])

    return call


def test_tool_call_matches_local_backend(handler):
    status, body = handler("get_purchase_history", {"account": "maya.r@example.com"})
    assert status == 200 and body["account_id"] == "ACC-1001" and len(body["purchases"]) == 3
    status, body = handler("search_kb", {"query": "forgot password"}, b64=True)
    assert body == JsonBackend().search_kb("forgot password")


@pytest.mark.parametrize(
    "body,fragment",
    [("not json", "not valid JSON"), ("[1]", "JSON object"), ({"acct": "x"}, "Unknown argument")],
)
def test_bad_requests_are_400(handler, body, fragment):
    status, out = handler("get_account_status", body)
    assert status == 400 and fragment in out["error"]


def test_missing_argument_is_400(handler):
    status, out = handler("get_account_status", {})
    assert status == 400 and "account" in out["error"]


def test_logs_one_structured_line(handler, capsys):
    handler("get_service_status", {})
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["tool"] == "get_service_status" and line["status"] == 200


def test_api_client_signs_requests(monkeypatch):
    import boto3

    session = boto3.Session(
        aws_access_key_id="AKIDEXAMPLE", aws_secret_access_key="secret", region_name="us-east-1"
    )
    sent = {}

    def fake_urlopen(req, timeout):
        sent["url"], sent["headers"], sent["body"] = req.full_url, dict(req.headers), req.data
        return io.BytesIO(b'{"tickets": []}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    api = ApiBackend("https://abc123.execute-api.us-east-1.amazonaws.com/", session=session)
    assert api.lookup_ticket(ticket_id="TCK-1") == {"tickets": []}
    assert sent["url"] == "https://abc123.execute-api.us-east-1.amazonaws.com/tools/lookup_ticket"
    assert json.loads(sent["body"]) == {"ticket_id": "TCK-1"}  # None args dropped
    auth = sent["headers"]["Authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256") and "/us-east-1/execute-api/" in auth


def test_region_from_url():
    assert _region_from_url("https://x.execute-api.eu-west-1.amazonaws.com") == "eu-west-1"
