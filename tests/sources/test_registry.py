from types import SimpleNamespace

import pytest

from app.sources import (
    DEFAULT_CONFIGS,
    SourceNotFoundError,
    SourceRegistry,
    merge_config,
)
from tests.sources.conftest import make_registry, no_network_handler

ALL_SOURCES = {
    "linkedin",
    "naukri",
    "indeed",
    "cutshort",
    "wellfound",
    "ycombinator",
    "instahyre",
    "foundit",
    "remoteok",
    "weworkremotely",
    "company_careers",
}


def test_registry_builds_all_eleven_sources() -> None:
    registry = make_registry(no_network_handler)

    assert set(registry.list_names()) == ALL_SOURCES
    for name in ALL_SOURCES:
        assert registry.get(name).get_source_name() == name


def test_unknown_source_raises() -> None:
    registry = make_registry(no_network_handler)

    with pytest.raises(SourceNotFoundError):
        registry.get("monsterboard")
    with pytest.raises(SourceNotFoundError):
        registry.get_config("monsterboard")


def test_exactly_three_sources_enabled_by_default() -> None:
    enabled = {name for name, config in DEFAULT_CONFIGS.items() if config.enabled}
    assert enabled == {"remoteok", "weworkremotely", "company_careers"}


def test_config_overrides_apply() -> None:
    override = DEFAULT_CONFIGS["remoteok"].model_copy(
        update={"enabled": False, "baseUrl": "http://test.local"}
    )
    registry = make_registry(no_network_handler, overrides={"remoteok": override})

    assert registry.get_config("remoteok").enabled is False
    assert registry.get("remoteok").config.baseUrl == "http://test.local"


def test_merge_config_db_state_wins() -> None:
    default = DEFAULT_CONFIGS["remoteok"]

    row = SimpleNamespace(enabled=False, baseUrl=None, rateLimitPerMinute=99, requiresAuth=True)
    merged = merge_config(default, row)  # type: ignore[arg-type]
    assert merged.enabled is False
    assert merged.rateLimitPerMinute == 99
    assert merged.requiresAuth is True
    assert merged.baseUrl == default.baseUrl  # row null falls back to default

    assert merge_config(default, None).enabled is False  # unknown to DB = not runnable
    assert merge_config(default, None).baseUrl == default.baseUrl


def test_connector_with_config_builds_fresh_instance() -> None:
    registry = make_registry(no_network_handler)
    config = DEFAULT_CONFIGS["remoteok"].model_copy(update={"enabled": False})

    connector = registry.connector_with_config("remoteok", config)

    assert connector is not registry.get("remoteok")
    assert connector.config.enabled is False
    with pytest.raises(SourceNotFoundError):
        registry.connector_with_config("nope", config)


def test_registry_construction_makes_no_network_calls() -> None:
    # no_network_handler raises on any request — construction must not trigger it.
    registry = make_registry(no_network_handler)
    assert isinstance(registry, SourceRegistry)
