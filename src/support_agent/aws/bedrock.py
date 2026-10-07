"""Claude on Amazon Bedrock, behind the same LangChain chat model the agent already uses.

``ChatAnthropic`` builds an ``anthropic`` SDK client internally; this subclass swaps in the SDK's
Bedrock Mantle client (Messages API on Bedrock, SigV4 with the default AWS credential chain).
Requests, tool calls, structured output and ``usage_metadata`` are unchanged, so token and cost
accounting in ``llm.py`` work as-is.
"""

from __future__ import annotations

import re
from functools import cached_property

from langchain_anthropic import ChatAnthropic

_DATE_SUFFIX = re.compile(r"-\d{8}$")


def bedrock_model_id(model: str) -> str:
    """``claude-haiku-4-5-20251001`` -> ``anthropic.claude-haiku-4-5`` (Mantle uses undated IDs)."""
    if model.startswith("anthropic."):
        return model
    return f"anthropic.{_DATE_SUFFIX.sub('', model)}"


class ChatAnthropicBedrock(ChatAnthropic):
    aws_region: str | None = None  # None: AWS_REGION / AWS_DEFAULT_REGION / profile

    @property
    def _llm_type(self) -> str:
        # Not "anthropic-chat": tells langchain-anthropic to use block-level cache_control.
        return "anthropic-bedrock-chat"

    def _mantle_params(self) -> dict:
        params: dict = {"aws_region": self.aws_region, "max_retries": self.max_retries}
        if self.default_headers:
            params["default_headers"] = self.default_headers
        if self.default_request_timeout is None or self.default_request_timeout > 0:
            params["timeout"] = self.default_request_timeout
        return params

    @cached_property
    def _client(self):
        from anthropic import AnthropicBedrockMantle

        return AnthropicBedrockMantle(**self._mantle_params())

    @cached_property
    def _async_client(self):
        from anthropic import AsyncAnthropicBedrockMantle

        return AsyncAnthropicBedrockMantle(**self._mantle_params())
