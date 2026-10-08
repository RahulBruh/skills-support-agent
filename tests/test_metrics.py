"""Per-skill CloudWatch metrics: what a triage publishes, and that failures are counted."""

import os

import pytest

from support_agent.api import AgentConfig, SupportAgent
from tests.conftest import FakeLLM
from tests.test_graph import billing_handler

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from support_agent.aws.metrics import NAMESPACE, CloudWatchMetrics  # noqa: E402


@pytest.fixture
def cloudwatch():
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        yield boto3.client("cloudwatch", region_name="us-east-1")


def _agent(handler, tools, cw):
    agent = SupportAgent(
        AgentConfig(today="2026-10-03"), llm_factory=lambda: FakeLLM(handler), tools=tools
    )
    agent._metrics = CloudWatchMetrics(client=cw)
    return agent


def _metrics(cw) -> dict[tuple[str, str | None], int]:
    out = {}
    for m in cw.list_metrics(Namespace=NAMESPACE)["Metrics"]:
        skill = next((d["Value"] for d in m["Dimensions"] if d["Name"] == "Skill"), None)
        out[(m["MetricName"], skill)] = 1
    return out


async def test_triage_publishes_per_skill_and_aggregate(local_tools, cloudwatch):
    agent = _agent(billing_handler, local_tools, cloudwatch)
    await agent.triage("charged twice", followups=["ACC-1001 on PC, ORD-50012"])
    published = _metrics(cloudwatch)
    for name in ("Triages", "Errors", "Latency", "Tokens", "Escalations", "ToolCalls"):
        assert (name, "billing") in published and (name, None) in published


async def test_failed_triage_counts_as_error(local_tools, cloudwatch):
    def broken(*_):
        raise RuntimeError("model down")

    agent = _agent(broken, local_tools, cloudwatch)
    with pytest.raises(RuntimeError):
        await agent.triage("help")
    assert ("Errors", "unrouted") in _metrics(cloudwatch)


def test_publishing_failure_never_raises(caplog):
    class Down:
        def put_metric_data(self, **_):
            raise ConnectionError("no network")

    CloudWatchMetrics(client=Down()).record_error("billing", 1.0)
    assert "Could not publish" in caplog.text
