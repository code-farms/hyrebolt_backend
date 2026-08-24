import json
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx

from app.sources import JobSourceConfig, SourceRegistry

FIXTURES = Path(__file__).parent / "fixtures"


def load_json_fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def load_text_fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def make_registry(
    handler: Callable[[httpx.Request], httpx.Response],
    overrides: Mapping[str, JobSourceConfig] | None = None,
) -> SourceRegistry:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SourceRegistry(http_client=client, config_overrides=overrides)


def no_network_handler(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected network call: {request.url}")
