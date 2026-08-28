import json

import httpx
import pytest

from app.ai import (
    ChatCompletionsProvider,
    LLMRateLimitedError,
    LLMResponseError,
    MockLLMProvider,
)
from app.ai.exceptions import LLMError, LLMUnavailableError

BASE_URL = "https://llm.example/v1"
MODEL = "test-model"


def make_provider(handler) -> ChatCompletionsProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ChatCompletionsProvider(client, api_key="sk-test", model=MODEL, base_url=BASE_URL)


def ok_response(content: dict, model: str = MODEL) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [{"message": {"content": json.dumps(content)}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 45},
        },
    )


async def test_chat_completions_request_shape_and_parsing() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return ok_response({"title": "Backend Engineer"})

    provider = make_provider(handler)
    result = await provider.complete_json(system="sys", prompt="user prompt")

    assert captured["url"] == f"{BASE_URL}/chat/completions"
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["model"] == MODEL
    assert captured["body"]["messages"][0] == {"role": "system", "content": "sys"}
    assert result.content == {"title": "Backend Engineer"}
    assert result.inputTokens == 120 and result.outputTokens == 45
    assert result.model == MODEL


async def test_chat_completions_base_url_trailing_slash_is_normalised() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return ok_response({"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ChatCompletionsProvider(
        client, api_key="k", model=MODEL, base_url="https://llm.example/v1beta/openai/"
    )
    await provider.complete_json(system="s", prompt="p")

    assert captured["url"] == "https://llm.example/v1beta/openai/chat/completions"


async def test_chat_completions_429_is_retryable_with_retry_after() -> None:
    provider = make_provider(lambda request: httpx.Response(429, headers={"Retry-After": "12"}))

    with pytest.raises(LLMRateLimitedError) as excinfo:
        await provider.complete_json(system="s", prompt="p")
    assert excinfo.value.retryable is True
    assert excinfo.value.retry_after == 12.0


async def test_chat_completions_5xx_retryable_and_4xx_not() -> None:
    with pytest.raises(LLMUnavailableError) as unavailable:
        await make_provider(lambda r: httpx.Response(503)).complete_json(system="s", prompt="p")
    assert unavailable.value.retryable is True

    with pytest.raises(LLMError) as rejected:
        await make_provider(lambda r: httpx.Response(400)).complete_json(system="s", prompt="p")
    assert rejected.value.retryable is False


async def test_chat_completions_bad_json_content_is_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json at all"}}]})

    with pytest.raises(LLMResponseError):
        await make_provider(handler).complete_json(system="s", prompt="p")


async def test_chat_completions_non_object_json_is_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "[1, 2]"}}]})

    with pytest.raises(LLMResponseError):
        await make_provider(handler).complete_json(system="s", prompt="p")


async def test_mock_provider_is_deterministic_and_never_invents() -> None:
    provider = MockLLMProvider()

    first = await provider.complete_json(system="s", prompt="Title: Backend Engineer\nrest")
    second = await provider.complete_json(system="s", prompt="Title: Backend Engineer\nrest")

    assert first.content == second.content
    assert first.content["title"] == "Backend Engineer"
    assert first.content["salary"] is None
    assert first.content["experienceMin"] is None
    assert provider.calls == 2
