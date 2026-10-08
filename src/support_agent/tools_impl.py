"""Plain-Python implementations of the shared support tools.

These are wrapped as MCP tools in ``mcp_server.py`` and as Lambda handlers in ``aws/lambdas.py``.
The tool logic lives in ``Backend``; subclasses differ only in where the data comes from:
``JsonBackend`` (local files) or ``DynamoBackend`` (DynamoDB, in ``aws/dynamo.py``).
``ApiBackend`` (``aws/http.py``) offers the same tool methods by calling the deployed Lambdas.
"""

from __future__ import annotations

import json
import math
import os
import re
from functools import lru_cache
from pathlib import Path

from .paths import default_data_dir

TOOL_NAMES = frozenset(
    {
        "lookup_ticket",
        "get_account_status",
        "get_purchase_history",
        "search_kb",
        "get_service_status",
    }
)


class Backend:
    """Tool logic shared by every data store. Subclasses provide the storage primitives
    (``_account`` ... ``_status``) and inherit lookups, masking, KB ranking and status matching."""

    # -- storage primitives -------------------------------------------------------------------
    def _account(self, key: str) -> dict | None:
        """Account record (without purchases) by account ID or email, case-insensitive."""
        raise NotImplementedError

    def _account_id(self, key: str) -> str | None:
        """Resolve an account ID or email to the canonical account ID."""
        a = self._account(key)
        return a["account_id"] if a else None

    def _purchases(self, account_id: str) -> list[dict]:
        raise NotImplementedError

    def _tickets(self, ticket_id: str) -> list[dict]:
        raise NotImplementedError

    def _tickets_for_account(self, account_id: str) -> list[dict]:
        raise NotImplementedError

    def _kb(self) -> list[dict]:
        raise NotImplementedError

    def _status(self) -> dict:
        """``{"as_of": ..., "games": {name: {"status": ..., "known_issues": [...]}}}``"""
        raise NotImplementedError

    # -- accounts -----------------------------------------------------------------------------
    def get_account_status(self, account: str) -> dict:
        a = self._account(account)
        if a is None:
            return {"found": False, "account": account}
        out = {k: v for k, v in a.items() if k not in ("purchases", "email")}
        out["email_masked"] = _mask_email(a["email"])
        out["found"] = True
        return out

    def get_purchase_history(self, account: str) -> dict:
        acc_id = self._account_id(account)
        if acc_id is None:
            return {"found": False, "account": account}
        return {"found": True, "account_id": acc_id, "purchases": self._purchases(acc_id)}

    # -- tickets ------------------------------------------------------------------------------
    def lookup_ticket(self, ticket_id: str | None = None, account: str | None = None) -> dict:
        if ticket_id:
            hits = self._tickets(ticket_id.strip())
        elif account:
            hits = self._tickets_for_account(self._account_id(account) or account.strip())
        else:
            return {"error": "Provide ticket_id or account."}
        return {"tickets": hits}

    # -- knowledge base -----------------------------------------------------------------------
    def search_kb(self, query: str, top_k: int = 3) -> dict:
        docs = [
            (art, _tokens(art["title"]), _tokens(" ".join(art["tags"])), _tokens(art["body"]))
            for art in self._kb()
        ]
        n = len(docs)
        scored = []
        for art, title, tags, body in docs:
            score = 0.0
            for t in set(_tokens(query)):
                df = sum(1 for _, ti, ta, bo in docs if t in ti or t in ta or t in bo)
                tf = 3 * title.count(t) + 2 * tags.count(t) + min(body.count(t), 3)
                score += tf * (math.log((n + 1) / (df + 0.5)) if df else 0)
            if score > 0:
                scored.append((round(score, 2), art))
        scored.sort(key=lambda s: -s[0])
        return {
            "results": [
                {"id": a["id"], "title": a["title"], "snippet": a["body"][:240], "score": s}
                for s, a in scored[: max(1, min(top_k, 5))]
            ]
        }

    # -- service status -----------------------------------------------------------------------
    def get_service_status(self, game: str | None = None) -> dict:
        status = self._status()
        games = status["games"]
        if not game:
            return {
                "as_of": status["as_of"],
                "games": {g: v["status"] for g, v in games.items()},
            }
        key = game.strip().lower()
        for name, info in games.items():
            if key in name.lower() or name.lower() in key:
                return {"as_of": status["as_of"], "game": name, **info}
        return {
            "as_of": status["as_of"],
            "game": game,
            "found": False,
            "known_games": list(games),
        }


class JsonBackend(Backend):
    """Reads the mock data files under ``data/``. The default; needs no AWS access."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir or default_data_dir())
        self.accounts = json.loads((self.data_dir / "accounts.json").read_text(encoding="utf-8"))
        self.tickets = json.loads((self.data_dir / "tickets.json").read_text(encoding="utf-8"))
        self.status = json.loads(
            (self.data_dir / "service_status.json").read_text(encoding="utf-8")
        )
        self.kb = load_kb(self.data_dir)

    def _account(self, key: str) -> dict | None:
        key = key.strip().lower()
        for a in self.accounts:
            if key in (a["account_id"].lower(), a["email"].lower()):
                return {k: v for k, v in a.items() if k != "purchases"}
        return None

    def _purchases(self, account_id: str) -> list[dict]:
        a = next(a for a in self.accounts if a["account_id"] == account_id)
        return a["purchases"]

    def _tickets(self, ticket_id: str) -> list[dict]:
        return [t for t in self.tickets if t["ticket_id"].lower() == ticket_id.lower()]

    def _tickets_for_account(self, account_id: str) -> list[dict]:
        return [t for t in self.tickets if t["account_id"].lower() == account_id.lower()]

    def _kb(self) -> list[dict]:
        return self.kb

    def _status(self) -> dict:
        return self.status


def load_kb(data_dir: Path) -> list[dict]:
    return [_parse_kb(p) for p in sorted((data_dir / "kb").glob("*.md"))]


def _parse_kb(path: Path) -> dict:
    import yaml

    text = path.read_text(encoding="utf-8")
    _, fm, body = text.split("---", 2)
    meta = yaml.safe_load(fm)
    return {
        "id": meta["id"],
        "title": meta["title"],
        "tags": meta.get("tags", []),
        "body": body.strip(),
    }


def _tokens(text: str) -> list[str]:
    words = [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2]
    return [w[:-1] if w.endswith("s") and len(w) > 4 and not w.endswith("ss") else w for w in words]


def _mask_email(email: str) -> str:
    user, _, domain = email.partition("@")
    return f"{user[0]}***@{domain}"


BACKENDS = ("json", "dynamodb", "api")


@lru_cache(maxsize=4)
def get_backend(kind: str | None = None) -> Backend:
    """The backend named by ``kind`` or ``$SUPPORT_AGENT_BACKEND`` (default ``json``)."""
    kind = kind or os.environ.get("SUPPORT_AGENT_BACKEND", "json")
    if kind == "json":
        return JsonBackend()
    if kind == "dynamodb":
        from .aws.dynamo import DynamoBackend

        return DynamoBackend()
    if kind == "api":
        from .aws.http import ApiBackend

        return ApiBackend()
    raise ValueError(f"Unknown backend {kind!r}; expected one of {BACKENDS}")
