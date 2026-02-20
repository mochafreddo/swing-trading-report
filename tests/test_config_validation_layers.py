from __future__ import annotations

import pytest
from sab.config import load_config


def _reset_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "SAB_CONFIG",
        "DATA_PROVIDER",
        "SCREEN_LIMIT",
        "REPORT_DIR",
        "DATA_DIR",
        "STRATEGY_MODE",
        "SELL_MODE",
        "FX_MODE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_load_config_normalizes_invalid_modes_from_env(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")

    _reset_config_env(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("STRATEGY_MODE", "invalid-mode")
    monkeypatch.setenv("SELL_MODE", "invalid-mode")
    monkeypatch.setenv("FX_MODE", "invalid-mode")

    cfg = load_config()

    assert cfg.strategy_mode == "ema_cross"
    assert cfg.sell_mode == "generic"
    assert cfg.fx_mode == "manual"


def test_load_config_applies_provider_and_limit_overrides(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
data:
  provider: pykrx
  screen_limit: 77
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config(provider_override="kis", limit_override=12)

    assert cfg.data_provider == "kis"
    assert cfg.screen_limit == 12


def test_load_config_empty_report_data_env_falls_back_to_yaml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
data:
  report_dir: custom-reports
  data_dir: custom-data
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("REPORT_DIR", "")
    monkeypatch.setenv("DATA_DIR", "")

    cfg = load_config()

    assert cfg.report_dir == "custom-reports"
    assert cfg.data_dir == "custom-data"
