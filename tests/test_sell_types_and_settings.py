from __future__ import annotations

from types import SimpleNamespace

from sab.sell_evaluation import _build_hybrid_sell_settings, _build_sell_settings
from sab.sell_types import (
    _exchange_from_suffix,
    _normalize_suffix,
    _split_symbol_and_suffix,
)
from sab.signals.hybrid_sell import HybridSellSettings
from sab.signals.sell_rules import SellSettings


def _make_cfg() -> SimpleNamespace:
    hybrid_sell = SimpleNamespace(
        profit_target_low=0.1,
        profit_target_high=0.2,
        partial_profit_floor=0.05,
        ema_short_period=5,
        ema_mid_period=20,
        sma_trend_period=60,
        rsi_period=14,
        stop_loss_pct_min=0.03,
        stop_loss_pct_max=0.05,
        failed_breakout_drop_pct=0.02,
        min_bars=20,
        time_stop_days=30,
        time_stop_grace_days=5,
        time_stop_profit_floor=0.01,
    )
    return SimpleNamespace(
        sell_atr_multiplier=2.0,
        sell_time_stop_days=20,
        sell_require_sma200=True,
        sell_ema_short=10,
        sell_ema_long=20,
        sell_rsi_period=14,
        sell_rsi_floor=30,
        sell_rsi_floor_alt=25,
        sell_min_bars=2,
        hybrid_sell=hybrid_sell,
    )


def test_sell_type_helpers_basic_behavior() -> None:
    assert _normalize_suffix("nas-daq") == "NASDAQ"
    assert _split_symbol_and_suffix("aapl.us") == ("AAPL", "US")
    assert _exchange_from_suffix("NASDAQ") == "NAS"


def test_sell_settings_builders_basic_behavior() -> None:
    cfg = _make_cfg()
    sell_settings = _build_sell_settings(cfg, SellSettingsCls=SellSettings)
    hybrid_settings = _build_hybrid_sell_settings(
        cfg, HybridSellSettingsCls=HybridSellSettings
    )
    assert sell_settings.atr_trail_multiplier == 2.0
    assert hybrid_settings.profit_target_low == 0.1
