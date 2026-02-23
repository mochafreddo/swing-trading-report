from __future__ import annotations

import pytest
from sab import env_loader
from sab.config import load_config
from sab.config_loader import ConfigLoadError


def _reset_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "SAB_CONFIG",
        "SAB_CONFIG_STRICT",
        "DATA_PROVIDER",
        "SCREEN_LIMIT",
        "REPORT_DIR",
        "DATA_DIR",
        "STRATEGY_MODE",
        "SELL_MODE",
        "FX_MODE",
        "GITHUB_ACTIONS",
        "CI",
        "MIN_DOLLAR_VOLUME",
    ):
        monkeypatch.delenv(key, raising=False)


def _force_fallback_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env_loader, "_load_with_python_dotenv", lambda **_: False)


def test_load_config_normalizes_invalid_modes_from_env(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("STRATEGY_MODE", "invalid-mode")
    monkeypatch.setenv("SELL_MODE", "invalid-mode")
    monkeypatch.setenv("FX_MODE", "invalid-mode")

    cfg = load_config()

    assert cfg.strategy_mode == "ema_cross"
    assert cfg.sell_mode == "generic"
    assert cfg.fx_mode == "manual"


def test_load_config_strict_mode_rejects_invalid_modes_from_env(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("STRATEGY_MODE", "invalid-mode")

    with pytest.raises(ConfigLoadError, match="Strict config parsing failed"):
        load_config()


def test_load_config_strict_mode_rejects_invalid_numeric_threshold(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("MIN_DOLLAR_VOLUME", "not-a-number")

    with pytest.raises(ConfigLoadError, match="Strict config parsing failed"):
        load_config()


def test_load_config_strict_mode_in_ci_cannot_be_disabled(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SAB_CONFIG_STRICT", "false")
    monkeypatch.setenv("STRATEGY_MODE", "invalid-mode")

    with pytest.raises(ConfigLoadError, match="Strict config parsing failed"):
        load_config()


def test_load_config_strict_mode_allows_optional_float_null(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
fx:
  usdkrw: null
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    cfg = load_config()
    assert cfg.usd_krw_rate is None


def test_load_config_strict_mode_rejects_empty_mode_from_env(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("STRATEGY_MODE", "")

    with pytest.raises(ConfigLoadError, match="Strict config parsing failed"):
        load_config()


def test_load_config_applies_provider_and_limit_overrides(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
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
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config(provider_override="kis", limit_override=12)

    assert cfg.data_provider == "kis"
    assert cfg.screen_limit == 12


def test_load_config_rejects_env_yaml_conflict_even_for_empty_env_value(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
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
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("REPORT_DIR", "")
    monkeypatch.setenv("DATA_DIR", "")

    with pytest.raises(
        ConfigLoadError, match="Config conflict policy violation"
    ) as exc:
        load_config()

    msg = str(exc.value)
    assert "DATA_DIR (data.data_dir)" in msg
    assert "REPORT_DIR (data.report_dir)" in msg
