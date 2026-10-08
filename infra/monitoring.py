"""CloudWatch dashboard and alarms for the agent (per skill) and the tool services (per tool).

Skills are discovered from ``skills/`` at synth time, so adding a SKILL.md and redeploying adds
its dashboard widgets and alarms with no code change, the same contract as the agent itself.
"""

from __future__ import annotations

from aws_cdk import Duration
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

from support_agent.aws.metrics import NAMESPACE

FIVE_MIN = Duration.minutes(5)


class Monitoring(Construct):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        prefix: str,
        skills: list[str],
        functions: dict[str, lambda_.Function],
        api: apigw.HttpApi,
        alarm_email: str | None = None,
        latency_p90_ms: int = 30_000,
        error_rate_pct: int = 10,
    ):
        super().__init__(scope, cid)
        self.prefix = prefix
        self.topic = sns.Topic(self, "Alarms", display_name=f"{prefix} alarms")
        if alarm_email:
            self.topic.add_subscription(subs.EmailSubscription(alarm_email))
        self.alarms: list[cw.Alarm] = []

        # -- agent, per skill -------------------------------------------------------------------
        for skill in skills:
            triages = _agent("Triages", skill, "Sum")
            errors = _agent("Errors", skill, "Sum")
            error_rate = cw.MathExpression(
                expression="IF(t > 0, 100 * e / t, 0)",
                using_metrics={"t": triages, "e": errors},
                period=Duration.minutes(15),
                label=f"{skill} error rate %",
            )
            self._alarm(
                f"{skill}-error-rate",
                error_rate,
                threshold=error_rate_pct,
                description=f"More than {error_rate_pct}% of {skill} triages failed in 15 min.",
            )
            self._alarm(
                f"{skill}-latency-p90",
                _agent("Latency", skill, "p90"),
                threshold=latency_p90_ms,
                periods=2,
                description=f"{skill} p90 triage latency above {latency_p90_ms / 1000:.0f}s "
                "for 10 min.",
            )

        # -- tool services, per tool ------------------------------------------------------------
        for tool, fn in functions.items():
            self._alarm(
                f"tool-{tool}-errors",
                fn.metric_errors(period=FIVE_MIN, statistic="Sum"),
                threshold=1,
                description=f"The {tool} Lambda raised errors (AccessDenied would show here).",
            )
            self._alarm(
                f"tool-{tool}-throttles",
                fn.metric_throttles(period=FIVE_MIN, statistic="Sum"),
                threshold=1,
                description=f"The {tool} Lambda is being throttled.",
            )

        # -- API --------------------------------------------------------------------------------
        self._alarm(
            "api-5xx",
            api.metric_server_error(period=FIVE_MIN, statistic="Sum"),
            threshold=1,
            description="The tool API returned 5xx responses.",
        )
        self._alarm(
            "api-latency-p90",
            api.metric_latency(period=FIVE_MIN, statistic="p90"),
            threshold=2000,
            periods=2,
            description="Tool API p90 latency above 2s for 10 min.",
        )

        self.dashboard = self._dashboard(prefix, skills, functions, api)

    def _alarm(self, name: str, metric, *, threshold: float, description: str, periods: int = 1):
        alarm = cw.Alarm(
            self,
            f"Alarm-{name}",
            alarm_name=f"{self.prefix}-{name}",
            alarm_description=description,
            metric=metric,
            threshold=threshold,
            evaluation_periods=periods,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )
        alarm.add_alarm_action(cw_actions.SnsAction(self.topic))
        alarm.add_ok_action(cw_actions.SnsAction(self.topic))
        self.alarms.append(alarm)
        return alarm

    def _dashboard(self, prefix, skills, functions, api) -> cw.Dashboard:
        def per_skill(metric: str, stat: str) -> list[cw.IMetric]:
            return [_agent(metric, s, stat, label=s) for s in skills]

        def per_tool(fn_metric: str, stat: str) -> list[cw.IMetric]:
            return [
                getattr(fn, fn_metric)(period=FIVE_MIN, statistic=stat, label=tool)
                for tool, fn in functions.items()
            ]

        def graph(title: str, left: list[cw.IMetric], width: int = 8, **kw) -> cw.GraphWidget:
            return cw.GraphWidget(title=title, left=left, width=width, height=6, **kw)

        d = cw.Dashboard(self, "Dashboard", dashboard_name=f"{prefix}-operations")
        d.add_widgets(
            cw.TextWidget(
                markdown=f"# {prefix}\nAgent metrics per **skill** (namespace `{NAMESPACE}`), "
                "then the tool services per **tool**. Alarms notify the SNS topic.",
                width=24,
                height=2,
            )
        )
        d.add_widgets(
            graph("Triages per skill", per_skill("Triages", "Sum"), stacked=True),
            graph("p90 latency per skill (ms)", per_skill("Latency", "p90")),
            graph("Errors per skill", per_skill("Errors", "Sum")),
        )
        d.add_widgets(
            graph("Avg cost per triage (USD)", per_skill("CostUSD", "Average")),
            graph("Escalation rate per skill", per_skill("Escalations", "Average")),
            graph("Avg tokens per triage", per_skill("Tokens", "Average")),
        )
        d.add_widgets(
            graph("Tool invocations", per_tool("metric_invocations", "Sum"), stacked=True),
            graph("Tool p90 duration (ms)", per_tool("metric_duration", "p90")),
            graph("Tool errors", per_tool("metric_errors", "Sum")),
        )
        d.add_widgets(
            graph(
                "API requests and errors",
                [
                    api.metric_count(period=FIVE_MIN, label="requests"),
                    api.metric_client_error(period=FIVE_MIN, label="4xx"),
                    api.metric_server_error(period=FIVE_MIN, label="5xx"),
                ],
                width=12,
            ),
            graph(
                "API latency (ms)",
                [
                    api.metric_latency(period=FIVE_MIN, statistic="p50", label="p50"),
                    api.metric_latency(period=FIVE_MIN, statistic="p90", label="p90"),
                ],
                width=12,
            ),
        )
        d.add_widgets(cw.AlarmStatusWidget(alarms=self.alarms, title="Alarms", width=24, height=4))
        return d


def _agent(metric: str, skill: str, stat: str, label: str | None = None) -> cw.Metric:
    return cw.Metric(
        namespace=NAMESPACE,
        metric_name=metric,
        dimensions_map={"Skill": skill},
        statistic=stat,
        period=FIVE_MIN,
        label=label,
    )
