"""provider="bedrock" builds a ChatAnthropic that talks to the Bedrock Mantle endpoint."""

import pytest

from support_agent.llm import make_chat_model

pytest.importorskip("boto3")

from support_agent.aws.bedrock import ChatAnthropicBedrock, bedrock_model_id  # noqa: E402


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-haiku-4-5-20251001", "anthropic.claude-haiku-4-5"),
        ("claude-sonnet-5-5", "anthropic.claude-sonnet-5-5"),
        ("anthropic.claude-opus-5-5", "anthropic.claude-opus-5-5"),
    ],
)
def test_bedrock_model_id(model, expected):
    assert bedrock_model_id(model) == expected


def test_bedrock_chat_model_uses_mantle_client(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    chat = make_chat_model("claude-haiku-4-5-20251001", provider="bedrock")
    assert isinstance(chat, ChatAnthropicBedrock)
    assert chat.model == "anthropic.claude-haiku-4-5"
    assert chat._llm_type != "anthropic-chat"
    client = chat._async_client
    assert type(client).__name__ == "AsyncAnthropicBedrockMantle"
    assert "bedrock-mantle.us-west-2" in str(client.base_url)


def test_unknown_provider():
    with pytest.raises(ValueError, match="provider"):
        make_chat_model("claude-haiku-4-5", provider="openai")
