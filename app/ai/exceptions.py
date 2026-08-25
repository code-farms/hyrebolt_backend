"""Plain exceptions (not AppException): LLM calls run inside services/workers
where callers decide whether a failure is fatal. `retryable` drives the
analysis service's retry loop, mirroring the SourceError taxonomy."""


class LLMError(Exception):
    retryable: bool = False

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class LLMUnavailableError(LLMError):
    """Network failure, timeout, or provider 5xx."""

    retryable = True


class LLMRateLimitedError(LLMError):
    retryable = True

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(message)


class LLMResponseError(LLMError):
    """The provider answered, but not with usable JSON."""
