from support_agent.api import _mcp_tools
from support_agent.paths import default_data_dir
from support_agent.tools_impl import TOOL_NAMES, Backend


def test_account_lookup_by_email_or_id_masks_email():
    b = Backend()
    by_id = b.get_account_status("ACC-1003")
    by_email = b.get_account_status("PRIYA.S@example.com")
    assert by_id == by_email
    assert "email" not in by_id and by_id["email_masked"] == "p***@example.com"
    assert "login_from_new_country" in by_id["flags"]


def test_unknown_account():
    assert Backend().get_purchase_history("nobody@example.com") == {
        "found": False,
        "account": "nobody@example.com",
    }


def test_kb_search_ranks_relevant_article_first():
    b = Backend()
    assert b.search_kb("refund playstation")["results"][0]["id"] == "KB-105"
    assert b.search_kb("forgot password")["results"][0]["id"] == "KB-201"
    assert b.search_kb("zzzz")["results"] == []


def test_service_status_fuzzy_game_match():
    s = Backend().get_service_status("starfall")
    assert s["game"] == "Starfall Arena" and s["known_issues"][0]["kb"] == "KB-302"


def test_tickets_by_account():
    assert [
        t["ticket_id"] for t in Backend().lookup_ticket(account="jordan.k@example.com")["tickets"]
    ] == ["TCK-7001"]


async def test_mcp_server_exposes_all_tools():
    async with _mcp_tools(default_data_dir()) as tools:
        assert {t.name for t in tools} == TOOL_NAMES
        search = next(t for t in tools if t.name == "search_kb")
        out = await search.ainvoke({"query": "pending charge"})
        assert "KB-102" in str(out)
