from __future__ import annotations

import pytest
from sab.config import _ENV_YAML_CONFLICT_BINDINGS, Config, load_config
from sab.config_loader import load_yaml_config


def _load_repository_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.delenv("SAB_CONFIG", raising=False)
    for env_key, _yaml_path in _ENV_YAML_CONFLICT_BINDINGS:
        monkeypatch.delenv(env_key, raising=False)
    return load_config()


def _load_example_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("SAB_CONFIG", "config.example.yaml")
    for env_key, _yaml_path in _ENV_YAML_CONFLICT_BINDINGS:
        monkeypatch.delenv(env_key, raising=False)
    return load_config()


def test_repository_config_evaluates_full_configured_screener_universe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _load_repository_config(monkeypatch)

    assert cfg.screen_limit >= cfg.screener_limit + cfg.us_screener_limit


def test_repository_config_has_entry_portfolio_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _load_repository_config(monkeypatch)

    assert cfg.portfolio.max_active_holdings is not None
    assert cfg.portfolio.max_new_entries_kr is not None
    assert cfg.portfolio.max_new_entries_us is not None


def test_repository_config_defaults_market_regime_unavailable_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _load_repository_config(monkeypatch)

    assert cfg.market_regime_unavailable_policy == "block_market"


def test_repository_config_enables_market_regime_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _load_repository_config(monkeypatch)

    assert cfg.use_market_regime_filter is True


def test_repository_config_defaults_entry_fatal_missing_price_ratio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _load_repository_config(monkeypatch)

    assert cfg.entry_fatal_missing_price_ratio == 0.0


def test_config_dataclass_defaults_match_active_safety_contract() -> None:
    cfg = Config()

    assert cfg.use_market_regime_filter is True
    assert cfg.market_regime_unavailable_policy == "block_market"
    assert cfg.entry_fatal_missing_price_ratio == 0.0


def test_entry_check_yaml_sections_only_expose_effective_threshold() -> None:
    repository_config = load_yaml_config("config.yaml").raw
    example_config = load_yaml_config("config.example.yaml").raw

    assert set(repository_config["entry_check"]) == {"fatal_missing_price_ratio"}
    assert set(example_config["entry_check"]) == {"fatal_missing_price_ratio"}


def test_example_config_keeps_fail_closed_scan_safety_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _load_example_config(monkeypatch)

    assert cfg.use_market_regime_filter is True
    assert cfg.market_regime_unavailable_policy == "block_market"
    assert cfg.entry_fatal_missing_price_ratio == 0.0
