import asyncio

import pytest

from app.ai.base import LLMProvider, LLMResult
from app.ai.exceptions import LLMRateLimitedError, LLMResponseError, LLMUnavailableError
from app.ai.retry import complete_json_with_retries
from tests.ai.test_analysis_service import ScriptedProvider


class SlowProvider(LLMProvider):
    async def complete_json(self, *, system: str, prompt: str) -> LLMResult:
        await asyncio.sleep(10)
        return LLMResult(content={}, model="slow")


async def call(provider, *, max_retries: int = 2, timeout: float = 5.0):
    sleeps: list[float] = []

    async def record(seconds: float) -> None:
        sleeps.append(seconds)

    result = await complete_json_with_retries(
        provider,
        system="s",
        prompt="p",
        timeout_seconds=timeout,
        max_retries=max_retries,
        base_delay=1.0,
        sleep=record,
    )
    return result, sleeps


async def test_retries_retryable_errors_with_backoff_and_retry_after_floor() -> None:
    provider = ScriptedProvider(
        [LLMUnavailableError("down"), LLMRateLimitedError("slow", retry_after=7.0), {"ok": True}]
    )
    result, sleeps = await call(provider)
    assert result.content == {"ok": True}
    assert sleeps == [1.0, 7.0]  # 1*2^0, then max(1*2^1, retry_after)


async def test_gives_up_after_max_retries() -> None:
    provider = ScriptedProvider([LLMUnavailableError("down")] * 3)
    with pytest.raises(LLMUnavailableError):
        await call(provider, max_retries=1)
    assert provider.calls == 2


async def test_non_retryable_error_is_raised_immediately() -> None:
    provider = ScriptedProvider([LLMResponseError("bad json"), {"never": 1}])
    with pytest.raises(LLMResponseError):
        await call(provider)
    assert provider.calls == 1


async def test_timeout_becomes_unavailable() -> None:
    with pytest.raises(LLMUnavailableError):
        await call(SlowProvider(), max_retries=0, timeout=0.01)
