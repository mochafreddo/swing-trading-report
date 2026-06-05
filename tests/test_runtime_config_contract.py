from __future__ import annotations

import pytest
from sab.config import _ENV_YAML_CONFLICT_BINDINGS, load_config


def _load_repository_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.delenv("SAB_CONFIG", raising=False)
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
