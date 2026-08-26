"""Retry loop shared by every LLM-backed service: per-attempt timeout,
exponential backoff on retryable provider errors, Retry-After honoured as a
delay floor. Scalars rather than Settings so callers can tune per use (the
gap analysis passes max_retries=0 — it is additive and must stay fast)."""

import asyncio
from collections.abc import Awaitable, Callable

from app.ai.base import LLMProvider, LLMResult
from app.ai.exceptions import LLMError, LLMRateLimitedError, LLMUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

Sleep = Callable[[float], Awaitable[None]]


async def complete_json_with_retries(
    provider: LLMProvider,
    *,
    system: str,
    prompt: str,
    timeout_seconds: float,
    max_retries: int,
    base_delay: float,
    sleep: Sleep = asyncio.sleep,
    event: str = "llm_retry",
) -> LLMResult:
    attempt = 0
    while True:
        attempt += 1
        try:
            async with asyncio.timeout(timeout_seconds):
                return await provider.complete_json(system=system, prompt=prompt)
        except TimeoutError as exc:
            error: LLMError = LLMUnavailableError("LLM call timed out")
            if attempt > max_retries:
                raise error from exc
        except LLMError as exc:
            if not exc.retryable or attempt > max_retries:
                raise
            error = exc
        delay = base_delay * (2 ** (attempt - 1))
        if isinstance(error, LLMRateLimitedError) and error.retry_after is not None:
            delay = max(delay, error.retry_after)
        logger.warning(event, attempt=attempt, delay_seconds=round(delay, 2))
        await sleep(delay)
