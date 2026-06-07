from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import sab.entry as entry
from sab.entry import run_entry
from sab.report.entry_report import EntryReportRow
from sab.report.supabase_storage import SupabaseStorageError


def _build_entry_candidate() -> dict[str, object]:
    return {
        "ticker": "AAPL.NASD",
        "eval_date": "20260226",
        "entry_reference_eval_date": "20260226",
        "entry_reference_close_raw_value": 100.0,
        "gap_guard_pct_value": 0.05,
    }


def _entry_price_result(price: float | None) -> entry.EntryPriceLookupResult:
    if price is None:
        return entry.EntryPriceLookupResult.missing(
            "provider_error",
            source="kis_live_snapshot",
        )
    return entry.EntryPriceLookupResult.available(price, source="kis_live_snapshot")


def test_run_entry_upload_flag_uses_supabase_upload_path(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "US"},
                "candidates": [_build_entry_candidate()],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key=None,
        kis_app_secret=None,
        kis_base_url=None,
        kis_min_interval_ms=None,
        entry_fatal_missing_price_ratio=1.0,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )
    monkeypatch.setattr(
        "sab.entry._make_price_lookup",
        lambda **_kwargs: (lambda _ticker: _entry_price_result(101.5), []),
    )

    upload_calls: list[dict[str, object]] = []

    def _fake_upload(  # type: ignore[no-untyped-def]
        *,
        artifact_path: str,
        run_type: str,
        logger,
        force: bool = False,
    ):
        upload_calls.append(
            {
                "artifact_path": artifact_path,
                "run_type": run_type,
                "logger_name": logger.name,
                "force": force,
            }
        )
        return "2026/02/2026-02-26.entry.json"

    monkeypatch.setattr("sab.entry.maybe_upload_report_artifact", _fake_upload)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
        upload=True,
    )

    assert exit_code == 0
    assert len(upload_calls) == 1
    assert upload_calls[0]["run_type"] == "entry"
    assert cast(str, upload_calls[0]["artifact_path"]).endswith(".entry.json")
    assert upload_calls[0]["force"] is True


def test_run_entry_upload_flag_returns_error_on_supabase_failure(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "US"},
                "candidates": [_build_entry_candidate()],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key=None,
        kis_app_secret=None,
        kis_base_url=None,
        kis_min_interval_ms=None,
        entry_fatal_missing_price_ratio=1.0,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )
    monkeypatch.setattr(
        "sab.entry._make_price_lookup",
        lambda **_kwargs: (lambda _ticker: _entry_price_result(101.5), []),
    )
    monkeypatch.setattr(
        "sab.entry.maybe_upload_report_artifact",
        lambda **_kwargs: (_ for _ in ()).throw(SupabaseStorageError("upload failed")),
    )

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
        upload=True,
    )

    assert exit_code == 1


def test_run_entry_upload_flag_skips_supabase_upload_when_price_gap_is_fatal(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "US"},
                "candidates": [_build_entry_candidate()],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key=None,
        kis_app_secret=None,
        kis_base_url=None,
        kis_min_interval_ms=None,
        entry_fatal_missing_price_ratio=1.0,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )
    monkeypatch.setattr(
        "sab.entry._make_price_lookup",
        lambda **_kwargs: (
            lambda _ticker: _entry_price_result(None),
            ["provider unavailable"],
        ),
    )

    upload_calls: list[dict[str, object]] = []

    def _fake_upload(**kwargs: object) -> str:
        upload_calls.append(kwargs)
        return "2026/02/2026-02-26.entry.json"

    monkeypatch.setattr("sab.entry.maybe_upload_report_artifact", _fake_upload)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
        upload=True,
    )

    assert exit_code == 1
    assert upload_calls == []
    assert len(list(report_dir.glob("*.entry.json"))) == 1


def test_entry_report_write_helper_skips_upload_after_fatal_missing_price(
    monkeypatch, tmp_path: Path
) -> None:
    assert hasattr(entry, "_write_entry_report_and_maybe_upload")
    helper = entry._write_entry_report_and_maybe_upload
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    out_path = report_dir / "2026-02-27.entry.json"
    row = EntryReportRow(
        ticker="AAPL.NASD",
        action="REVIEW",
        reasons=["price snapshot unavailable"],
        signal_close=100.0,
        entry_price=None,
        gap_pct=None,
    )
    write_calls: list[dict[str, object]] = []

    def _fake_write_entry_report(**kwargs: object) -> str:
        write_calls.append(kwargs)
        return out_path.as_posix()

    upload_calls: list[dict[str, object]] = []

    def _fake_upload(**kwargs: object) -> str:
        upload_calls.append(kwargs)
        return "2026/02/2026-02-27.entry.json"

    monkeypatch.setattr("sab.entry.write_entry_report", _fake_write_entry_report)
    monkeypatch.setattr("sab.entry.maybe_upload_report_artifact", _fake_upload)

    callback_paths: list[str] = []
    exit_code = helper(
        report_dir=report_dir.as_posix(),
        artifact={"market": "MIXED"},
        entries=[row],
        run_meta={"run_id": "entry-test"},
        entry_summary={"missing_entry_price_ratio": 1.0},
        system_issues=["AAPL.NASD: price snapshot unavailable"],
        entry_session_date=None,
        entry_session_date_by_market={"US": "2026-02-26", "KR": "2026-02-27"},
        fatal_missing_price_ratio=1.0,
        upload=True,
        report_path_callback=callback_paths.append,
    )

    assert exit_code == 1
    assert write_calls[0]["entries"] == [row]
    assert write_calls[0]["artifact_date"] == "2026-02-27"
    assert callback_paths == [out_path.as_posix()]
    assert upload_calls == []


def test_run_entry_uses_config_threshold_instead_of_env(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "US"},
                "candidates": [
                    _build_entry_candidate(),
                    {
                        **_build_entry_candidate(),
                        "ticker": "MSFT.NASD",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key=None,
        kis_app_secret=None,
        kis_base_url=None,
        kis_min_interval_ms=None,
        entry_fatal_missing_price_ratio=1.0,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )
    monkeypatch.setenv("ENTRY_FATAL_MISSING_PRICE_RATIO", "0.0")
    monkeypatch.setattr(
        "sab.entry._make_price_lookup",
        lambda **_kwargs: (
            lambda ticker: (
                _entry_price_result(None)
                if ticker == "AAPL.NASD"
                else _entry_price_result(101.5)
            ),
            [],
        ),
    )

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
        upload=False,
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.entry.json")).read_text("utf-8"))
    assert payload["summary"]["missing_entry_price_ratio"] == 0.5
    assert payload["config_snapshot"]["entry_fatal_missing_price_ratio"] == 1.0


def test_run_entry_threshold_zero_fails_on_partial_missing_price(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "US"},
                "candidates": [
                    _build_entry_candidate(),
                    {
                        **_build_entry_candidate(),
                        "ticker": "MSFT.NASD",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key=None,
        kis_app_secret=None,
        kis_base_url=None,
        kis_min_interval_ms=None,
        entry_fatal_missing_price_ratio=0.0,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )
    monkeypatch.setattr(
        "sab.entry._make_price_lookup",
        lambda **_kwargs: (
            lambda ticker: (
                _entry_price_result(None)
                if ticker == "AAPL.NASD"
                else _entry_price_result(101.5)
            ),
            [],
        ),
    )

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
        upload=True,
    )

    assert exit_code == 1
    payload = json.loads(next(report_dir.glob("*.entry.json")).read_text("utf-8"))
    assert payload["summary"]["missing_entry_price_ratio"] == 0.5
    assert payload["config_snapshot"]["entry_fatal_missing_price_ratio"] == 0.0
