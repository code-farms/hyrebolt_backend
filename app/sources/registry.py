from collections.abc import Mapping

import httpx

from app.db.generated.models import JobSource as JobSourceRow
from app.sources.base import JobSourceConnector
from app.sources.connectors import CONNECTOR_CLASSES
from app.sources.exceptions import SourceNotFoundError
from app.sources.http import SourceHTTPClient, Throttle
from app.sources.models import JobSourceConfig, SourceCapability

_C = SourceCapability

# Code-side defaults for every known source. Operator state (enabled, rate
# limit, base URL overrides) lives on the JobSource DB row and wins via
# merge_config; capabilities and extra stay code-side.
DEFAULT_CONFIGS: dict[str, JobSourceConfig] = {
    "linkedin": JobSourceConfig(
        name="linkedin",
        displayName="LinkedIn",
        baseUrl="https://www.linkedin.com",
        requiresAuth=True,
        capabilities=(_C.SEARCH, _C.DETAILS),
    ),
    "naukri": JobSourceConfig(
        name="naukri",
        displayName="Naukri",
        baseUrl="https://www.naukri.com",
        capabilities=(_C.SEARCH, _C.DETAILS),
    ),
    "indeed": JobSourceConfig(
        name="indeed",
        displayName="Indeed",
        baseUrl="https://www.indeed.com",
        capabilities=(_C.SEARCH, _C.DETAILS),
    ),
    "cutshort": JobSourceConfig(
        name="cutshort",
        displayName="Cutshort",
        baseUrl="https://cutshort.io",
        requiresAuth=True,
        capabilities=(_C.SEARCH,),
    ),
    "wellfound": JobSourceConfig(
        name="wellfound",
        displayName="Wellfound",
        baseUrl="https://wellfound.com",
        requiresAuth=True,
        capabilities=(_C.SEARCH, _C.STARTUP_METADATA),
    ),
    "ycombinator": JobSourceConfig(
        name="ycombinator",
        displayName="Y Combinator / Work at a Startup",
        baseUrl="https://www.workatastartup.com",
        requiresAuth=True,
        capabilities=(_C.SEARCH, _C.STARTUP_METADATA),
    ),
    "instahyre": JobSourceConfig(
        name="instahyre",
        displayName="Instahyre",
        baseUrl="https://www.instahyre.com",
        requiresAuth=True,
        capabilities=(_C.SEARCH,),
    ),
    "foundit": JobSourceConfig(
        name="foundit",
        displayName="Foundit",
        baseUrl="https://www.foundit.in",
        capabilities=(_C.SEARCH,),
    ),
    "remoteok": JobSourceConfig(
        name="remoteok",
        displayName="Remote OK",
        enabled=True,
        baseUrl="https://remoteok.com",
        rateLimitPerMinute=10,
        capabilities=(_C.API, _C.SEARCH),
    ),
    "weworkremotely": JobSourceConfig(
        name="weworkremotely",
        displayName="We Work Remotely",
        enabled=True,
        baseUrl="https://weworkremotely.com",
        rateLimitPerMinute=10,
        capabilities=(_C.FEED, _C.SEARCH),
    ),
    "company_careers": JobSourceConfig(
        name="company_careers",
        displayName="Company career pages",
        enabled=True,
        rateLimitPerMinute=30,
        capabilities=(_C.API, _C.SEARCH, _C.SCRAPE_PERMITTED_PAGES, _C.STARTUP_METADATA),
        extra={"boards": []},
    ),
}


def merge_config(default: JobSourceConfig, row: JobSourceRow | None) -> JobSourceConfig:
    """Pure merge of the operator state from a JobSource DB row over the code
    default. A source unknown to the DB is never runnable."""
    if row is None:
        return default.model_copy(update={"enabled": False})
    return default.model_copy(
        update={
            "enabled": row.enabled,
            "baseUrl": row.baseUrl or default.baseUrl,
            "rateLimitPerMinute": (
                row.rateLimitPerMinute
                if row.rateLimitPerMinute is not None
                else default.rateLimitPerMinute
            ),
            "requiresAuth": row.requiresAuth,
        }
    )


class SourceRegistry:
    """Builds and hands out connectors. Never talks to the DB or the network
    itself — the injected httpx client is only used when a connector method is
    invoked."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        config_overrides: Mapping[str, JobSourceConfig] | None = None,
        throttle: Throttle | None = None,
    ) -> None:
        self._http_client = http_client
        self._throttle = throttle
        self._configs = {**DEFAULT_CONFIGS, **dict(config_overrides or {})}
        self._connectors = {
            name: self._build(name, config) for name, config in self._configs.items()
        }

    def get(self, name: str) -> JobSourceConnector:
        try:
            return self._connectors[name]
        except KeyError:
            raise SourceNotFoundError(name, "unknown source") from None

    def get_config(self, name: str) -> JobSourceConfig:
        try:
            return self._configs[name]
        except KeyError:
            raise SourceNotFoundError(name, "unknown source") from None

    def list_names(self) -> list[str]:
        return sorted(self._connectors)

    def list_all(self) -> list[JobSourceConnector]:
        return [self._connectors[name] for name in self.list_names()]

    def connector_with_config(
        self, name: str, config: JobSourceConfig, throttle: Throttle | None = None
    ) -> JobSourceConnector:
        """Fresh connector with a (e.g. DB-merged) config and an optional
        per-source throttle — the discovery engine's entry point."""
        if name not in self._configs:
            raise SourceNotFoundError(name, "unknown source")
        return self._build(name, config, throttle=throttle)

    def _build(
        self, name: str, config: JobSourceConfig, throttle: Throttle | None = None
    ) -> JobSourceConnector:
        connector_class = CONNECTOR_CLASSES[name]
        http = SourceHTTPClient(
            self._http_client,
            source_name=name,
            timeout_seconds=config.timeoutSeconds,
            throttle=throttle if throttle is not None else self._throttle,
        )
        return connector_class(config, http)
