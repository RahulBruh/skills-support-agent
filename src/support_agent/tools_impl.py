"""Plain-Python implementations of the shared support tools.

These are wrapped as MCP tools in ``mcp_server.py``. Keeping them as pure functions makes them
unit-testable without an MCP session.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

import yaml

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
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir or default_data_dir())
        self.accounts = json.loads((self.data_dir / "accounts.json").read_text(encoding="utf-8"))
        self.tickets = json.loads((self.data_dir / "tickets.json").read_text(encoding="utf-8"))
        self.status = json.loads(
            (self.data_dir / "service_status.json").read_text(encoding="utf-8")
        )
        self.kb = [_parse_kb(p) for p in sorted((self.data_dir / "kb").glob("*.md"))]

    # -- accounts -----------------------------------------------------------------------------
    def _find_account(self, account: str) -> dict | None:
        key = account.strip().lower()
        for a in self.accounts:
            if key in (a["account_id"].lower(), a["email"].lower()):
                return a
        return None

    def get_account_status(self, account: str) -> dict:
        a = self._find_account(account)
        if a is None:
            return {"found": False, "account": account}
        out = {k: v for k, v in a.items() if k not in ("purchases", "email")}
        out["email_masked"] = _mask_email(a["email"])
        out["found"] = True
        return out

    def get_purchase_history(self, account: str) -> dict:
        a = self._find_account(account)
        if a is None:
            return {"found": False, "account": account}
        return {"found": True, "account_id": a["account_id"], "purchases": a["purchases"]}

    # -- tickets ------------------------------------------------------------------------------
    def lookup_ticket(self, ticket_id: str | None = None, account: str | None = None) -> dict:
        if ticket_id:
            hits = [t for t in self.tickets if t["ticket_id"].lower() == ticket_id.strip().lower()]
        elif account:
            a = self._find_account(account)
            acc_id = a["account_id"] if a else account
            hits = [t for t in self.tickets if t["account_id"].lower() == acc_id.lower()]
        else:
            return {"error": "Provide ticket_id or account."}
        return {"tickets": hits}

    # -- knowledge base -----------------------------------------------------------------------
    def search_kb(self, query: str, top_k: int = 3) -> dict:
        docs = [
            (art, _tokens(art["title"]), _tokens(" ".join(art["tags"])), _tokens(art["body"]))
            for art in self.kb
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
        games = self.status["games"]
        if not game:
            return {
                "as_of": self.status["as_of"],
                "games": {g: v["status"] for g, v in games.items()},
            }
        key = game.strip().lower()
        for name, info in games.items():
            if key in name.lower() or name.lower() in key:
                return {"as_of": self.status["as_of"], "game": name, **info}
        return {
            "as_of": self.status["as_of"],
            "game": game,
            "found": False,
            "known_games": list(games),
        }


def _parse_kb(path: Path) -> dict:
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


@lru_cache(maxsize=4)
def get_backend(data_dir: str | None = None) -> Backend:
    return Backend(Path(data_dir) if data_dir else None)
