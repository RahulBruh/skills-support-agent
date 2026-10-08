"""Per-skill operational metrics in CloudWatch.

Every triage publishes one datum per metric, both with a ``Skill`` dimension and without one
(the all-skills aggregate). The CDK stack builds one dashboard row and a set of alarms per skill
from the same names, so a new SKILL.md gets monitoring on its next deploy.
"""

from __future__ import annotations

import logging

from ..models import TriageResult

NAMESPACE = "SupportAgent"
UNKNOWN_SKILL = "unrouted"  # failures before routing finished

# metric name -> CloudWatch unit
METRICS = {
    "Triages": "Count",
    "Errors": "Count",
    "Latency": "Milliseconds",
    "Tokens": "Count",
    "CostUSD": "None",
    "Escalations": "Count",
    "ToolCalls": "Count",
}

log = logging.getLogger(__name__)


class CloudWatchMetrics:
    def __init__(self, provider: str = "anthropic", *, client=None):
        import boto3

        self.cw = client or boto3.client("cloudwatch")
        self.provider = provider

    def record(self, result: TriageResult) -> None:
        values = {
            "Triages": 1,
            "Errors": 0,
            "Latency": result.latency_s * 1000,
            "Tokens": result.usage.total_tokens,
            "Escalations": int(result.escalate),
            "ToolCalls": len(result.tool_calls),
        }
        if result.cost_usd is not None:
            values["CostUSD"] = result.cost_usd
        self._put(result.skill, values)

    def record_error(self, skill: str | None, latency_s: float) -> None:
        self._put(skill or UNKNOWN_SKILL, {"Triages": 1, "Errors": 1, "Latency": latency_s * 1000})

    def _put(self, skill: str, values: dict[str, float]) -> None:
        data = []
        for name, value in values.items():
            for dims in ([{"Name": "Skill", "Value": skill}], []):
                data.append(
                    {"MetricName": name, "Dimensions": dims, "Value": value, "Unit": METRICS[name]}
                )
        try:
            self.cw.put_metric_data(Namespace=NAMESPACE, MetricData=data)
        except Exception:  # monitoring must never fail a triage
            log.warning("Could not publish CloudWatch metrics", exc_info=True)
