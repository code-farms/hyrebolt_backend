"""Provider for any OpenAI-compatible chat-completions endpoint (Gemini, OpenAI,
Groq, OpenRouter, Ollama, ...) using raw httpx (no SDK): keeps the dependency
surface small and makes the wire protocol MockTransport-testable. The vendor is
selected purely by base_url + model. JSON mode is enforced via response_format."""

import json

import httpx

from app.ai.base import LLMProvider, LLMResult
from app.ai.exceptions import (
    LLMError,
    LLMRateLimitedError,
    LLMResponseError,
    LLMUnavailableError,
)


class ChatCompletionsProvider(LLMProvider):
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def complete_json(self, *, system: str, prompt: str) -> LLMResult:
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError("LLM API request timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(f"LLM API network error: {exc}") from exc

        if response.status_code == 429:
            retry_after_header = response.headers.get("Retry-After")
            retry_after = (
                float(retry_after_header)
                if retry_after_header and retry_after_header.replace(".", "", 1).isdigit()
                else None
            )
            raise LLMRateLimitedError("LLM API rate limit hit", retry_after=retry_after)
        if response.status_code >= 500:
            raise LLMUnavailableError(f"LLM API returned {response.status_code}")
        if response.status_code >= 400:
            raise LLMError(f"LLM API rejected the request ({response.status_code})")

        try:
            body = response.json()
            message_content = body["choices"][0]["message"]["content"]
            content = json.loads(message_content)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError(f"unparseable LLM API response: {exc}") from exc
        if not isinstance(content, dict):
            raise LLMResponseError("model returned JSON that is not an object")

        usage = body.get("usage") or {}
        return LLMResult(
            content=content,
            model=body.get("model", self._model),
            inputTokens=usage.get("prompt_tokens"),
            outputTokens=usage.get("completion_tokens"),
        )
