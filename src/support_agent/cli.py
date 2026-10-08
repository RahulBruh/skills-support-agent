from __future__ import annotations

import asyncio
import json
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .api import AgentConfig, SupportAgent
from .llm import DEFAULT_MODEL, PROVIDERS
from .models import TriageResult
from .paths import resolve_skills_dir
from .skills import validate_skills
from .tools_impl import BACKENDS

app = typer.Typer(help="Skills-driven player-support triage agent.", no_args_is_help=True)
skills_app = typer.Typer(help="Inspect and validate SKILL.md files.", no_args_is_help=True)
app.add_typer(skills_app, name="skills")
aws_app = typer.Typer(help="Manage the AWS deployment's data.", no_args_is_help=True)
app.add_typer(aws_app, name="aws")
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):  # Windows consoles default to cp1252
        _stream.reconfigure(encoding="utf-8", errors="replace")
console = Console()

Model = Annotated[str, typer.Option(help="Claude model ID (first-party form).")]
Provider = Annotated[
    str, typer.Option(help="Where Claude runs: anthropic (API key) | bedrock (AWS credentials).")
]
SkillsDir = Annotated[
    str | None, typer.Option(help="Skills directory (path or name, e.g. skills_v1).")
]
Mode = Annotated[str, typer.Option(help="Context loading: progressive | inline_all.")]
BackendOpt = Annotated[
    str,
    typer.Option("--backend", help="Tool data source: json | dynamodb | api (deployed Lambdas)."),
]


def _config(
    model: str,
    skills_dir: str | None,
    context_mode: str,
    backend: str = "json",
    provider: str = "anthropic",
) -> AgentConfig:
    if context_mode not in ("progressive", "inline_all"):
        raise typer.BadParameter("context-mode must be 'progressive' or 'inline_all'")
    if provider not in PROVIDERS:
        raise typer.BadParameter(f"provider must be one of {', '.join(PROVIDERS)}")
    if backend not in BACKENDS:
        raise typer.BadParameter(f"backend must be one of {', '.join(BACKENDS)}")
    return AgentConfig(
        model=model,
        skills_dir=skills_dir,
        context_mode=context_mode,
        backend=backend,
        provider=provider,
    )


@app.command()
def chat(
    model: Model = DEFAULT_MODEL,
    skills_dir: SkillsDir = None,
    context_mode: Mode = "progressive",
    backend: BackendOpt = "json",
    provider: Provider = "anthropic",
):
    """Interactive triage: describe a problem; the agent asks follow-ups, then decides."""

    async def ask_player(question: str) -> str | None:
        console.print(f"\n[bold cyan]Agent:[/] {question}")
        return console.input("[bold green]You:[/] ").strip() or None

    async def main():
        async with SupportAgent(
            _config(model, skills_dir, context_mode, backend, provider)
        ) as agent:
            names = ", ".join(agent.skills)
            console.print(f"[dim]Loaded skills: {names}. Empty reply skips a question.[/]")
            message = console.input("[bold green]You:[/] ")
            result = await agent.triage(message, reply_provider=ask_player)
            console.print(f"\n[bold cyan]Agent:[/] {result.reply}")
            _print_result(result)

    asyncio.run(main())


@app.command()
def run(
    message: str,
    followup: Annotated[
        list[str] | None, typer.Option(help="Scripted answers to intake questions.")
    ] = None,
    model: Model = DEFAULT_MODEL,
    skills_dir: SkillsDir = None,
    context_mode: Mode = "progressive",
    backend: BackendOpt = "json",
    provider: Provider = "anthropic",
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the full TriageResult as JSON.")
    ] = False,
):
    """Single-shot triage of MESSAGE."""

    async def main():
        async with SupportAgent(
            _config(model, skills_dir, context_mode, backend, provider)
        ) as agent:
            return await agent.triage(message, followups=followup or [])

    result = asyncio.run(main())
    if as_json:
        print(result.model_dump_json(indent=2))
    else:
        console.print(f"[bold cyan]Agent:[/] {result.reply}")
        _print_result(result)


@skills_app.command("list")
def list_skills(skills_dir: SkillsDir = None):
    """List skills and what they declare."""
    path = resolve_skills_dir(skills_dir)
    skills, errors = validate_skills(path)
    table = Table(title=f"Skills in {path}")
    for col in ("name", "required fields", "tools", "description"):
        table.add_column(col, overflow="fold")
    for s in skills.values():
        table.add_row(
            s.name, ", ".join(s.required_fields), ", ".join(s.allowed_tools), s.description[:80]
        )
    console.print(table)
    for e in errors:
        console.print(f"[red]invalid:[/] {e}")


@skills_app.command("validate")
def validate(skills_dir: SkillsDir = None):
    """Validate every SKILL.md; exits 1 on any error."""
    path = resolve_skills_dir(skills_dir)
    skills, errors = validate_skills(path)
    for e in errors:
        console.print(f"[red]ERROR[/] {e}")
    if errors:
        raise typer.Exit(1)
    console.print(f"[green]OK[/] {len(skills)} skills valid in {path}: {', '.join(skills)}")


@aws_app.command("seed")
def aws_seed(
    prefix: Annotated[
        str | None, typer.Option(help="Table name prefix (default $SUPPORT_AGENT_TABLE_PREFIX).")
    ] = None,
):
    """Load data/ into the DynamoDB tables. Idempotent; uses your default AWS credentials."""
    from .aws.dynamo import seed, table_name

    for entity, n in seed(prefix).items():
        console.print(f"[green]OK[/] {n:>3} items -> {table_name(entity, prefix)}")


def _print_result(r: TriageResult) -> None:
    t = Table(show_header=False, box=None)
    t.add_row("skill", f"{r.skill} (confidence {r.route_confidence:.2f})")
    t.add_row("priority", r.priority)
    t.add_row(
        "escalate", f"{r.escalate}" + (f" ({r.escalation_reason})" if r.escalation_reason else "")
    )
    t.add_row("fields", json.dumps(r.fields))
    t.add_row("tools", ", ".join(c.tool for c in r.tool_calls) or "-")
    t.add_row("kb", ", ".join(r.kb_articles) or "-")
    cost = f"${r.cost_usd:.4f}" if r.cost_usd is not None else "n/a"
    t.add_row(
        "usage",
        f"{r.usage.input_tokens} in / {r.usage.output_tokens} out, {r.usage.llm_calls} calls, "
        f"{cost}, {r.latency_s:.1f}s",
    )
    console.rule("[bold]Triage")
    console.print(t)


if __name__ == "__main__":
    app()
