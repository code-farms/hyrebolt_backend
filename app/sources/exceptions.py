"""Source errors are plain exceptions, deliberately NOT AppException: they
occur inside the discovery pipeline/workers where one failing source must
never fail the whole run. The pipeline catches them and records partial
failure; an API route that wants to surface one translates it explicitly."""


class SourceError(Exception):
    #: Phase 5's retry policy branches on this flag (backoff + retry when True).
    retryable: bool = False

    def __init__(self, source_name: str, message: str) -> None:
        self.source_name = source_name
        self.message = message
        super().__init__(f"[{source_name}] {message}")


class SourceNotFoundError(SourceError):
    """Registry lookup for an unknown source name."""


class SourceDisabledError(SourceError):
    """The connector exists but has no legitimate access path (or is switched
    off). Carries the documented reason."""


class SourceAuthRequiredError(SourceError):
    """The upstream rejected us with 401/403, or credentials are required and
    absent. Never work around this — see docs/job-sources.md."""


class SourceUnavailableError(SourceError):
    """Network failure, timeout, or upstream 5xx."""

    retryable = True


class SourceRateLimitedError(SourceError):
    """Upstream 429."""

    retryable = True

    def __init__(
        self, source_name: str, message: str, retry_after: float | None = None
    ) -> None:
        self.retry_after = retry_after
        super().__init__(source_name, message)


class SourceParseError(SourceError):
    """The upstream payload did not match the expected shape."""
