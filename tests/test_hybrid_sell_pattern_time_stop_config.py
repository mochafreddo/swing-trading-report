from __future__ import annotations

import pytest
from sab import env_loader
from sab.config import load_config
from sab.config_loader import ConfigLoadError


def _reset_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "SAB_CONFIG",
        "SAB_CONFIG_STRICT",
        "GITHUB_ACTIONS",
        "CI",
        "HYBRID_SELL_TIME_STOP_DAYS",
        "HYBRID_SELL_TIME_STOP_GRACE_DAYS",
        "HYBRID_SELL_TIME_STOP_PROFIT_FLOOR",
    ):
        monkeypatch.delenv(key, raising=False)


def _force_fallback_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env_loader, "_load_with_python_dotenv", lambda **_: False)


def test_load_config_parses_hybrid_sell_pattern_time_stop_overrides(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sell:
  hybrid:
    time_stop_days: 30
    time_stop_grace_days: 15
    time_stop_profit_floor: 0.03
    pattern_time_stops:
      swing_high_breakout:
        time_stop_days: 10
        time_stop_grace_days: 2
        time_stop_profit_floor: 0.01
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()

    breakout_stop = cfg.hybrid_sell.pattern_time_stops["swing_high_breakout"]
    assert breakout_stop.time_stop_days == 10
    assert breakout_stop.time_stop_grace_days == 2
    assert breakout_stop.time_stop_profit_floor == 0.01


@pytest.mark.parametrize(
    ("yaml_text", "error_path"),
    [
        (
            """
sell:
  hybrid:
    pattern_time_stops: []
""",
            "sell.hybrid.pattern_time_stops",
        ),
        (
            """
sell:
  hybrid:
    pattern_time_stops:
      unknown_pattern:
        time_stop_days: 10
""",
            "sell.hybrid.pattern_time_stops.unknown_pattern",
        ),
        (
            """
sell:
  hybrid:
    pattern_time_stops:
      swing_high_breakout:
        time_stop_days: -1
""",
            "sell.hybrid.pattern_time_stops.swing_high_breakout.time_stop_days",
        ),
    ],
)
def test_load_config_rejects_invalid_hybrid_sell_pattern_time_stops(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    yaml_text: str,
    error_path: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml_text.strip() + "\n", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(ConfigLoadError, match=error_path):
        load_config()
