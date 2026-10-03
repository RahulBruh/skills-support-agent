"""MCP server exposing the shared support tools to every skill.

Run standalone with ``python -m support_agent.mcp_server`` (stdio transport). Any MCP client,
including Claude Desktop or Claude Code, can connect to it.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .tools_impl import get_backend

mcp = FastMCP("player-support-tools")


@mcp.tool()
def lookup_ticket(ticket_id: str | None = None, account: str | None = None) -> dict:
    """Look up support tickets by ticket ID (e.g. TCK-7001) or list all tickets for an account
    (account ID like ACC-1001 or email)."""
    return get_backend().lookup_ticket(ticket_id=ticket_id, account=account)


@mcp.tool()
def get_account_status(account: str) -> dict:
    """Get account status, security flags, 2FA state and any suspension for an account ID
    (ACC-xxxx) or email. Does not return purchases."""
    return get_backend().get_account_status(account)


@mcp.tool()
def get_purchase_history(account: str) -> dict:
    """List an account's purchases: order ID, item, amount (USD), date, store, status
    (completed/pending/refunded), delivered and used flags."""
    return get_backend().get_purchase_history(account)


@mcp.tool()
def search_kb(query: str, top_k: int = 3) -> dict:
    """Search the player-support knowledge base. Returns article IDs (KB-xxx), titles and snippets."""
    return get_backend().search_kb(query, top_k)


@mcp.tool()
def get_service_status(game: str | None = None) -> dict:
    """Get live service status and known issues for a game (omit `game` for an overview)."""
    return get_backend().get_service_status(game)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
