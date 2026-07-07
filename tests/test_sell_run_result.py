from __future__ import annotations

import sab.sell as sell


def test_run_sell_with_result_returns_callback_report_path(monkeypatch) -> None:
    def _fake_run_sell(**kwargs: object) -> int:
        callback = kwargs["report_path_callback"]
        assert callable(callback)
        callback("reports/2026-07-06.sell.json")
        return 0

    monkeypatch.setattr(sell, "run_sell", _fake_run_sell)

    result = sell.run_sell_with_result(provider="kis", holdings_path="holdings.yaml")

    assert result.exit_code == 0
    assert result.report_path == "reports/2026-07-06.sell.json"


def test_run_sell_with_result_forwards_report_date(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_run_sell(**kwargs: object) -> int:
        captured.update(kwargs)
        callback = kwargs["report_path_callback"]
        assert callable(callback)
        callback("reports/2026-07-06.sell.json")
        return 0

    monkeypatch.setattr(sell, "run_sell", _fake_run_sell)

    result = sell.run_sell_with_result(
        provider="kis",
        holdings_path="holdings.yaml",
        report_date="2026-07-06",
    )

    assert result.exit_code == 0
    assert captured["report_date"] == "2026-07-06"
