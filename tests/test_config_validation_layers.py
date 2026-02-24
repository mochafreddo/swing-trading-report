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
        "HOLDINGS_FILE",
        "REPORT_DIR",
        "DATA_DIR",
        "UNIVERSE_MARKETS",
        "MARKET_CACHE_STALE_SESSIONS_KR",
        "MARKET_CACHE_STALE_SESSIONS_US",
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


def test_load_config_applies_holdings_and_markets_overrides(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
data:
  provider: pykrx
universe:
  markets:
    - KR
files:
  holdings: holdings.yaml
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "holdings.yaml").write_text(
        """
holdings:
  - ticker: 005930
    quantity: 1
    entry_price: 70000
""".strip()
        + "\n",
        encoding="utf-8",
    )
    override_holdings = tmp_path / "holdings.generated.yaml"
    override_holdings.write_text(
        """
holdings:
  - ticker: AAPL.NAS
    quantity: 2
    entry_price: 180
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config(
        holdings_override=str(override_holdings),
        markets_override=["US"],
    )

    assert cfg.holdings_path == str(override_holdings)
    assert [item.ticker for item in cfg.holdings.holdings] == ["AAPL.NAS"]
    assert cfg.universe_markets == ["US"]


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


@pytest.mark.parametrize(
    ("yaml_text", "error_path"),
    [
        ("sell:\n  atr_trail_multiplier: 0\n", "sell.atr_trail_multiplier"),
        ("sell:\n  time_stop_days: -1\n", "sell.time_stop_days"),
        (
            "sell:\n  hybrid:\n    profit_target_low: 0.11\n    profit_target_high: 0.10\n",
            "sell.hybrid.profit_target_low",
        ),
        (
            "sell:\n  hybrid:\n    stop_loss_pct_min: 0.06\n    stop_loss_pct_max: 0.05\n",
            "sell.hybrid.stop_loss_pct_min",
        ),
        (
            "sell:\n  hybrid:\n    failed_breakout_drop_pct: -0.01\n",
            "sell.hybrid.failed_breakout_drop_pct",
        ),
        ("strategy:\n  min_history_bars: 0\n", "strategy.min_history_bars"),
        ("sell:\n  rsi_period: 0\n", "sell.rsi_period"),
    ],
)
def test_load_config_rejects_invalid_risk_ranges_even_when_not_strict(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    yaml_text: str,
    error_path: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml_text, encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(ConfigLoadError, match=error_path):
        load_config()


def test_load_config_allows_zero_gap_atr_multiplier(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
strategy:
  gap_atr_multiplier: 0
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()
    assert cfg.gap_atr_multiplier == 0.0


def test_load_config_defaults_market_cache_staleness_to_zero_sessions(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()
    assert cfg.market_cache_stale_sessions_kr == 0
    assert cfg.market_cache_stale_sessions_us == 0
