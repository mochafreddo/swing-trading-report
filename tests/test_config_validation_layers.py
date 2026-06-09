from __future__ import annotations

import re

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
        "USE_MARKET_REGIME_FILTER",
        "MARKET_REGIME_UNAVAILABLE_POLICY",
        "ENTRY_FATAL_MISSING_PRICE_RATIO",
        "SELL_MODE",
        "FX_MODE",
        "GITHUB_ACTIONS",
        "CI",
        "MIN_DOLLAR_VOLUME",
        "RS_BENCHMARK_RETURN",
        "RS_BENCHMARK_TICKER_KR",
        "RS_BENCHMARK_TICKER_US",
        "HYBRID_RSI_ZONE_LOW",
        "HYBRID_RSI_ZONE_HIGH",
        "HYBRID_RSI_OVERSOLD_LOW",
        "HYBRID_RSI_OVERSOLD_HIGH",
        "HYBRID_BREAKOUT_CONS_MAX_RANGE_PCT",
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


def test_load_config_strict_mode_rejects_invalid_boolean_from_env(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("USE_MARKET_REGIME_FILTER", "maybe")

    with pytest.raises(ConfigLoadError, match="Strict config parsing failed"):
        load_config()


def test_load_config_strict_mode_rejects_invalid_boolean_from_yaml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
strategy:
  use_market_regime_filter: maybe
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    with pytest.raises(ConfigLoadError, match="Strict config parsing failed"):
        load_config()


@pytest.mark.parametrize("env_value", ["maybe", ""])
def test_load_config_rejects_invalid_market_regime_filter_env_without_strict(
    tmp_path, monkeypatch: pytest.MonkeyPatch, env_value: str
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("USE_MARKET_REGIME_FILTER", env_value)

    with pytest.raises(ConfigLoadError, match="USE_MARKET_REGIME_FILTER"):
        load_config()


def test_load_config_rejects_invalid_market_regime_filter_yaml_without_strict(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "strategy:\n"
        "  use_market_regime_filter: maybe\n"
        "  market_regime_unavailable_policy: block_market\n"
        "entry_check:\n"
        "  fatal_missing_price_ratio: 0.0\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(ConfigLoadError, match=r"strategy\.use_market_regime_filter"):
        load_config()


def test_load_config_custom_yaml_inherits_active_safety_defaults(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.local.yaml"
    config_path.write_text("data:\n  provider: kis\n", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()

    assert cfg.use_market_regime_filter is True
    assert cfg.market_regime_unavailable_policy == "block_market"
    assert cfg.entry_fatal_missing_price_ratio == 0.0


def test_load_config_missing_yaml_inherits_active_safety_defaults(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)

    cfg = load_config()

    assert cfg.use_market_regime_filter is True
    assert cfg.market_regime_unavailable_policy == "block_market"
    assert cfg.entry_fatal_missing_price_ratio == 0.0


@pytest.mark.parametrize(
    ("env_key", "env_value", "yaml_text", "yaml_path"),
    [
        (
            "USE_MARKET_REGIME_FILTER",
            "false",
            "strategy:\n  mode: sma_ema_hybrid\n",
            "strategy.use_market_regime_filter",
        ),
        (
            "MARKET_REGIME_UNAVAILABLE_POLICY",
            "warn_continue",
            "strategy:\n  mode: sma_ema_hybrid\n",
            "strategy.market_regime_unavailable_policy",
        ),
        (
            "ENTRY_FATAL_MISSING_PRICE_RATIO",
            "0.25",
            "entry_check:\n  enabled: false\n",
            "entry_check.fatal_missing_price_ratio",
        ),
    ],
)
def test_load_config_rejects_safety_env_when_loaded_yaml_omits_key(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    env_value: str,
    yaml_text: str,
    yaml_path: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml_text, encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv(env_key, env_value)

    with pytest.raises(ConfigLoadError, match=env_key) as exc:
        load_config()
    assert yaml_path in str(exc.value)
    assert "omits" in str(exc.value)
    assert "put operational safety keys in YAML" in str(exc.value)


def test_load_config_uses_active_market_regime_unavailable_policy_default_when_yaml_loaded(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("strategy:\n  mode: sma_ema_hybrid\n", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()

    assert cfg.market_regime_unavailable_policy == "block_market"


def test_load_config_parses_market_regime_unavailable_policy_from_yaml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "strategy:\n"
        "  mode: sma_ema_hybrid\n"
        "  market_regime_unavailable_policy: block_market\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()

    assert cfg.market_regime_unavailable_policy == "block_market"


def test_load_config_parses_market_regime_unavailable_policy_from_env_without_yaml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("MARKET_REGIME_UNAVAILABLE_POLICY", "block_market")

    cfg = load_config()

    assert cfg.market_regime_unavailable_policy == "block_market"


def test_load_config_normalizes_market_regime_unavailable_policy_from_env_without_yaml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("MARKET_REGIME_UNAVAILABLE_POLICY", " BLOCK_MARKET ")

    cfg = load_config()

    assert cfg.market_regime_unavailable_policy == "block_market"


def test_load_config_rejects_invalid_market_regime_unavailable_policy_without_strict(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "strategy:\n  market_regime_unavailable_policy: maybe\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(
        ConfigLoadError, match="MARKET_REGIME_UNAVAILABLE_POLICY"
    ) as exc:
        load_config()
    assert "Strict config parsing failed" not in str(exc.value)


def test_load_config_rejects_invalid_market_regime_unavailable_policy_env_without_strict(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("MARKET_REGIME_UNAVAILABLE_POLICY", "maybe")

    with pytest.raises(
        ConfigLoadError, match="MARKET_REGIME_UNAVAILABLE_POLICY"
    ) as exc:
        load_config()
    assert "Strict config parsing failed" not in str(exc.value)


def test_load_config_rejects_null_market_regime_unavailable_policy_without_strict(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "strategy:\n  market_regime_unavailable_policy: null\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(
        ConfigLoadError, match="MARKET_REGIME_UNAVAILABLE_POLICY"
    ) as exc:
        load_config()
    assert "Strict config parsing failed" not in str(exc.value)
    assert "config.yaml 'strategy.market_regime_unavailable_policy'" in str(exc.value)
    assert "null" in str(exc.value)


@pytest.mark.parametrize("yaml_text", ["strategy:\n", "entry_check:\n"])
def test_load_config_rejects_empty_safety_sections_without_strict(
    tmp_path, monkeypatch: pytest.MonkeyPatch, yaml_text: str
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml_text, encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(ConfigLoadError, match="must be a mapping"):
        load_config()


@pytest.mark.parametrize(
    ("yaml_text", "section_name"),
    [
        ("strategy: {}\n", "strategy"),
        ("entry_check: {}\n", "entry_check"),
    ],
)
def test_load_config_rejects_empty_safety_mapping_sections_without_strict(
    tmp_path, monkeypatch: pytest.MonkeyPatch, yaml_text: str, section_name: str
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml_text, encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(ConfigLoadError, match=section_name) as exc:
        load_config()
    assert "must not be empty" in str(exc.value)
    assert "Strict config parsing failed" not in str(exc.value)


@pytest.mark.parametrize(
    ("yaml_text", "section_name"),
    [
        ("strategy: []\n", "strategy"),
        ("strategy: warn_continue\n", "strategy"),
        ("entry_check: []\n", "entry_check"),
        ("entry_check: 1.0\n", "entry_check"),
    ],
)
def test_load_config_rejects_non_mapping_safety_sections_without_strict(
    tmp_path, monkeypatch: pytest.MonkeyPatch, yaml_text: str, section_name: str
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml_text, encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(ConfigLoadError, match=section_name) as exc:
        load_config()
    assert "must be a mapping" in str(exc.value)
    assert "Strict config parsing failed" not in str(exc.value)


@pytest.mark.parametrize(
    ("yaml_text", "path_name"),
    [
        (
            "strategy.market_regime_unavailable_policy: garbage\n",
            "strategy.market_regime_unavailable_policy",
        ),
        (
            "strategy.use_market_regime_filter: false\n",
            "strategy.use_market_regime_filter",
        ),
        (
            "entry_check.fatal_missing_price_ratio: -1\n",
            "entry_check.fatal_missing_price_ratio",
        ),
    ],
)
def test_load_config_rejects_top_level_dotted_safety_keys_without_strict(
    tmp_path, monkeypatch: pytest.MonkeyPatch, yaml_text: str, path_name: str
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml_text, encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(ConfigLoadError, match=re.escape(path_name)) as exc:
        load_config()
    assert "top-level dotted key" in str(exc.value)
    assert "Strict config parsing failed" not in str(exc.value)


def test_load_config_rejects_top_level_dotted_market_regime_filter_with_env_override(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "strategy.use_market_regime_filter: false\n"
        "strategy:\n"
        "  market_regime_unavailable_policy: block_market\n"
        "entry_check:\n"
        "  fatal_missing_price_ratio: 0.0\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("USE_MARKET_REGIME_FILTER", "false")

    with pytest.raises(
        ConfigLoadError, match=r"strategy\.use_market_regime_filter"
    ) as exc:
        load_config()
    assert "top-level dotted key" in str(exc.value)
    assert "Strict config parsing failed" not in str(exc.value)


def test_load_config_rejects_top_level_dotted_config_binding_key(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "kis.base_url: https://openapi.example.invalid\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(ConfigLoadError, match=r"kis\.base_url") as exc:
        load_config()
    assert "top-level dotted key" in str(exc.value)


def test_load_config_uses_active_entry_fatal_missing_price_ratio_default_when_yaml_loaded(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("entry_check:\n  enabled: false\n", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()

    assert cfg.entry_fatal_missing_price_ratio == 0.0


def test_load_config_parses_entry_fatal_missing_price_ratio_from_yaml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "entry_check:\n  enabled: false\n  fatal_missing_price_ratio: 0.0\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()

    assert cfg.entry_fatal_missing_price_ratio == 0.0


def test_load_config_parses_entry_fatal_missing_price_ratio_upper_bound_from_yaml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "entry_check:\n  fatal_missing_price_ratio: 1.0\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()

    assert cfg.entry_fatal_missing_price_ratio == 1.0


def test_load_config_parses_entry_fatal_missing_price_ratio_from_env_without_yaml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("ENTRY_FATAL_MISSING_PRICE_RATIO", "0.25")

    cfg = load_config()

    assert cfg.entry_fatal_missing_price_ratio == 0.25


def test_load_config_rejects_bool_entry_fatal_missing_price_ratio_from_yaml_without_strict(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "entry_check:\n  fatal_missing_price_ratio: false\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(
        ConfigLoadError, match=r"entry_check\.fatal_missing_price_ratio"
    ):
        load_config()


def test_load_config_rejects_null_entry_fatal_missing_price_ratio_without_strict(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "entry_check:\n  fatal_missing_price_ratio: null\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(
        ConfigLoadError, match=r"entry_check\.fatal_missing_price_ratio"
    ) as exc:
        load_config()
    assert "null" in str(exc.value)


@pytest.mark.parametrize("env_value", ["nan", "not-a-number"])
def test_load_config_rejects_invalid_entry_fatal_missing_price_ratio_env_without_strict(
    tmp_path, monkeypatch: pytest.MonkeyPatch, env_value: str
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("ENTRY_FATAL_MISSING_PRICE_RATIO", env_value)

    with pytest.raises(
        ConfigLoadError, match=r"entry_check\.fatal_missing_price_ratio"
    ):
        load_config()


def test_load_config_rejects_out_of_range_entry_fatal_missing_price_ratio_without_strict(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "entry_check:\n  fatal_missing_price_ratio: 1.25\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(
        ConfigLoadError, match=r"entry_check\.fatal_missing_price_ratio"
    ):
        load_config()


def test_load_config_rejects_negative_entry_fatal_missing_price_ratio_without_strict(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "entry_check:\n  fatal_missing_price_ratio: -0.5\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(
        ConfigLoadError, match=r"entry_check\.fatal_missing_price_ratio"
    ):
        load_config()


def test_load_config_rejects_market_regime_policy_env_yaml_conflict(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "strategy:\n  market_regime_unavailable_policy: warn_continue\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("MARKET_REGIME_UNAVAILABLE_POLICY", "block_market")

    with pytest.raises(ConfigLoadError, match="MARKET_REGIME_UNAVAILABLE_POLICY"):
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


def test_load_config_parses_market_benchmark_tickers(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
strategy:
  rs_benchmark_ticker_kr: 069500
  rs_benchmark_ticker_us: spy.ams
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()

    assert cfg.rs_benchmark_ticker_kr == "069500"
    assert cfg.rs_benchmark_ticker_us == "SPY.AMS"


def test_load_config_rejects_invalid_us_benchmark_ticker(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
strategy:
  rs_benchmark_ticker_us: SPY.US
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(ConfigLoadError, match=r"strategy\.rs_benchmark_ticker_us"):
        load_config()


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
    entry_currency: USD
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
    assert cfg.holdings.holdings == []
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


@pytest.mark.parametrize("ticker", ["AAPL.XNAS", "005930", "AAPL.US"])
def test_load_config_rejects_invalid_us_screener_defaults_ticker(
    tmp_path, monkeypatch: pytest.MonkeyPatch, ticker: str
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (f"screener:\n  us_defaults:\n    - {ticker}\n"),
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(ConfigLoadError, match=r"screener\.us_defaults"):
        load_config()


def test_load_config_normalizes_us_screener_defaults_to_canonical_exchange(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "screener:\n"
            "  us_defaults:\n"
            "    - aapl.nas-daq\n"
            "    - ibm.nyse\n"
            "    - spy.amex\n"
        ),
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()
    assert cfg.us_screener_defaults == ["AAPL.NAS", "IBM.NYS", "SPY.AMS"]


def test_load_config_normalizes_rs_benchmark_tickers(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "strategy:\n"
            "  rs_benchmark_ticker_kr: 069500\n"
            "  rs_benchmark_ticker_us: spy.amex\n"
        ),
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()
    assert cfg.rs_benchmark_ticker_kr == "069500"
    assert cfg.rs_benchmark_ticker_us == "SPY.AMS"


def test_load_config_parses_hybrid_breakout_max_range_pct(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
strategy:
  hybrid:
    breakout_consolidation_max_range_pct: 0.08
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()
    assert cfg.hybrid.breakout_consolidation_max_range_pct == 0.08


@pytest.mark.parametrize(
    ("yaml_text", "error_path"),
    [
        (
            "strategy:\n  rs_benchmark_ticker_us: SPY.US\n",
            "strategy.rs_benchmark_ticker_us",
        ),
        (
            "strategy:\n  rs_benchmark_ticker_kr: SPY.AMS\n",
            "strategy.rs_benchmark_ticker_kr",
        ),
    ],
)
def test_load_config_rejects_invalid_rs_benchmark_tickers(
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
        (
            "strategy:\n  hybrid:\n    rsi_zone_low: 61\n    rsi_zone_high: 60\n",
            "strategy.hybrid.rsi_zone_low",
        ),
        (
            "strategy:\n  hybrid:\n    rsi_oversold_low: 41\n    rsi_oversold_high: 40\n",
            "strategy.hybrid.rsi_oversold_low",
        ),
        (
            "strategy:\n  hybrid:\n    rsi_zone_low: .nan\n",
            "strategy.hybrid.rsi_zone_low",
        ),
        (
            "strategy:\n  hybrid:\n    rsi_zone_high: .inf\n",
            "strategy.hybrid.rsi_zone_high",
        ),
        (
            "strategy:\n  hybrid:\n    rsi_oversold_low: 101\n",
            "strategy.hybrid.rsi_oversold_low",
        ),
        (
            "strategy:\n  hybrid:\n    rsi_oversold_high: 100.1\n",
            "strategy.hybrid.rsi_oversold_high",
        ),
        (
            "strategy:\n  hybrid:\n    breakout_consolidation_max_range_pct: 0\n",
            "strategy.hybrid.breakout_consolidation_max_range_pct",
        ),
        (
            "strategy:\n  hybrid:\n    breakout_consolidation_max_range_pct: .nan\n",
            "strategy.hybrid.breakout_consolidation_max_range_pct",
        ),
        (
            "strategy:\n  hybrid:\n    breakout_consolidation_max_range_pct: .inf\n",
            "strategy.hybrid.breakout_consolidation_max_range_pct",
        ),
        (
            "strategy:\n  hybrid:\n    max_gap_pct: .nan\n",
            "strategy.hybrid.max_gap_pct",
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


def test_load_config_rejects_non_finite_hybrid_breakout_max_range_env(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("HYBRID_BREAKOUT_CONS_MAX_RANGE_PCT", "nan")

    with pytest.raises(
        ConfigLoadError,
        match=r"strategy\.hybrid\.breakout_consolidation_max_range_pct",
    ):
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


def test_load_config_parses_portfolio_caps(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
portfolio:
  max_active_holdings: 5
  max_new_entries_per_market:
    KR: 2
    US: 1
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()
    assert cfg.portfolio.max_active_holdings == 5
    assert cfg.portfolio.max_new_entries_kr == 2
    assert cfg.portfolio.max_new_entries_us == 1


@pytest.mark.parametrize(
    ("yaml_text", "error_path"),
    [
        ("portfolio:\n  max_active_holdings: -1\n", "portfolio.max_active_holdings"),
        (
            "portfolio:\n  max_active_holdings: true\n",
            "portfolio.max_active_holdings",
        ),
        (
            "portfolio:\n  max_new_entries_per_market:\n    KR: -1\n",
            "portfolio.max_new_entries_per_market.KR",
        ),
        (
            "portfolio:\n  max_new_entries_per_market:\n    KR: true\n",
            "portfolio.max_new_entries_per_market.KR",
        ),
        (
            "portfolio:\n  max_new_entries_per_market:\n    JP: 1\n",
            "portfolio.max_new_entries_per_market",
        ),
        (
            "portfolio:\n  max_new_entries_per_market: 3\n",
            "portfolio.max_new_entries_per_market",
        ),
    ],
)
def test_load_config_rejects_invalid_portfolio_config(
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
