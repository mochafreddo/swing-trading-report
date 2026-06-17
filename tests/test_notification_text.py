from __future__ import annotations

import pytest
from sab.report import notification_text
from sab.report.notification_text import (
    build_ai_brief_skipped_telegram_text,
    build_ai_brief_slack_summary_text,
    build_ai_brief_telegram_report_text,
    build_scan_slack_summary_text,
    build_scan_telegram_report_text,
    build_sell_slack_summary_text,
    build_sell_telegram_report_text,
)


def _assert_balanced_html_tags(parts: list[str]) -> None:
    for part in parts:
        assert part.count("<b>") == part.count("</b>")
        assert part.count("<code>") == part.count("</code>")
        assert part.count("<a href=") == part.count("</a>")


def test_build_scan_telegram_report_text_includes_buy_candidates() -> None:
    report = {
        "generated_at": "2026-02-11 21:03 KST",
        "summary": {"candidate_count": 3, "issue_count": 1},
        "candidates": [
            {
                "ticker": "GS.NYS",
                "name": "골드만삭스",
                "price": "$948.99",
                "score": "7.0",
                "entry_state": "READY",
                "entry_state_reason": "Pullback bounce confirmed",
            },
            {
                "ticker": "SYK.NYS",
                "name": "스트라이커",
                "price": "$361.06",
                "score": "7.0",
                "entry_state": "READY",
                "entry_state_reason": "RSI crossed above 50",
            },
            {
                "ticker": "MDT.NYS",
                "name": "메드트로닉",
                "price": "$101.42",
                "score": "6.5",
                "entry_state": "READY",
                "entry_state_reason": "Reversal candle near EMA short",
            },
        ],
    }

    text = build_scan_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/123",
        provider="kis",
        universe="both",
        storage_key="2026/02/2026-02-11.buy.json",
        max_items=5,
    )

    assert "[SAB] 매수 후보" in text
    assert "시장: 국내+미국 / 데이터: KIS" in text
    assert "시각: 2026-02-11 21:03 KST" in text
    assert "진입 가능: 3건" in text
    assert (
        "1. GS.NYS 골드만삭스 | $948.99 | 점수 7.0 | Pullback bounce confirmed" in text
    )
    assert "2. SYK.NYS 스트라이커 | $361.06 | 점수 7.0 | RSI crossed above 50" in text
    assert (
        "3. MDT.NYS 메드트로닉 | $101.42 | 점수 6.5 | Reversal candle near EMA short"
        in text
    )
    assert "보관: 2026/02/2026-02-11.buy.json" in text
    assert text.endswith("실행: https://github.com/example/repo/actions/runs/123")


def test_build_scan_telegram_report_text_handles_zero_candidates() -> None:
    report = {
        "generated_at": "2026-02-11 21:03 KST",
        "summary": {"candidate_count": 0, "issue_count": 0},
        "candidates": [],
    }

    text = build_scan_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/123",
        provider="kis",
        universe="KR",
    )

    assert "진입 가능: 0건" in text
    assert "진입 가능 후보 없음" in text


def test_build_scan_telegram_report_text_includes_all_ready_candidates_only() -> None:
    candidates = []
    for idx in range(7):
        entry_state = "WATCH" if idx == 2 else "READY"
        candidates.append(
            {
                "ticker": f"T{idx:03d}",
                "name": f"Name{idx}",
                "price": f"${100 + idx}",
                "score": "6.0",
                "entry_state": entry_state,
                "entry_state_reason": f"Reason {idx}",
            }
        )

    report = {
        "generated_at": "2026-02-11 21:03 KST",
        "summary": {"candidate_count": 7, "issue_count": 0},
        "candidates": candidates,
    }

    text = build_scan_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/987",
        provider="kis",
        universe="US",
        max_items=5,
    )

    assert "진입 가능: 6건" in text
    assert "외 " not in text
    assert "T002 Name2" not in text
    assert "T006 Name6" in text


def test_build_scan_telegram_report_text_keeps_legacy_candidates_without_entry_state() -> (
    None
):
    report = {
        "generated_at": "2026-02-11 21:03 KST",
        "summary": {"candidate_count": 1, "issue_count": 0},
        "candidates": [
            {
                "ticker": "LEGACY.NYS",
                "name": "Legacy Candidate",
                "price": "$120",
                "score": "6.8",
                "risk_guide": "Stop $112 / Target $136",
            }
        ],
    }

    text = build_scan_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/988",
        provider="kis",
        universe="US",
    )

    assert "진입 가능: 1건" in text
    assert "LEGACY.NYS Legacy Candidate" in text


def test_split_telegram_message_text_keeps_parts_within_limit() -> None:
    assert hasattr(notification_text, "split_telegram_message_text")

    text = "\n".join(f"{idx}. T{idx:03d}.NYS | $100 | 점수 6.0" for idx in range(12))
    parts = notification_text.split_telegram_message_text(text, max_chars=80)

    assert len(parts) > 1
    assert all(0 < len(part) <= 80 for part in parts)
    assert "\n".join(parts) == text


def test_build_sell_telegram_report_text_excludes_hold_rows() -> None:
    report = {
        "generated_at": "2026-02-11 21:00 KST",
        "summary": {
            "evaluated_count": 4,
            "issue_count": 0,
            "action_counts": {"SELL": 1, "REVIEW": 2, "HOLD": 1},
        },
        "evaluated": [
            {
                "ticker": "CMG.NYS",
                "action": "SELL",
                "pnl_pct": 0.123,
                "reasons": ["Hard stop triggered"],
            },
            {
                "ticker": "COP.NYS",
                "action": "REVIEW",
                "pnl_pct": 0.088,
                "reasons": ["Reached profit target zone"],
            },
            {
                "ticker": "CI.NYS",
                "action": "HOLD",
                "pnl_pct": 0.014,
                "reasons": ["No hybrid sell criteria triggered"],
            },
            {
                "ticker": "MSI.NYS",
                "action": "REVIEW",
                "pnl_pct": -0.034,
                "reasons": ["Close below EMA short"],
            },
        ],
    }

    text = build_sell_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/456",
        provider="kis",
        include_actions=("SELL", "REVIEW"),
        storage_key="2026/02/2026-02-11.sell.json",
        max_items=5,
    )

    assert "[SAB] 매도 점검" in text
    assert "데이터: KIS" in text
    assert "시각: 2026-02-11 21:00 KST" in text
    assert "대상: 3건 (매도 1, 점검 2, 보유 1 제외)" in text
    assert "CMG.NYS | 매도 | +12.3% | Hard stop triggered" in text
    assert "COP.NYS | 점검 | +8.8% | Reached profit target zone" in text
    assert "MSI.NYS | 점검 | -3.4% | Close below EMA short" in text
    assert "CI.NYS" not in text
    assert "보관: 2026/02/2026-02-11.sell.json" in text
    assert text.endswith("실행: https://github.com/example/repo/actions/runs/456")


def test_build_sell_telegram_report_text_handles_hold_only() -> None:
    report = {
        "generated_at": "2026-02-11 21:00 KST",
        "summary": {
            "evaluated_count": 2,
            "issue_count": 0,
            "action_counts": {"HOLD": 2},
        },
        "evaluated": [
            {
                "ticker": "CI.NYS",
                "action": "HOLD",
                "pnl_pct": 0.012,
                "reasons": ["No hybrid sell criteria triggered"],
            },
            {
                "ticker": "JPM.NYS",
                "action": "HOLD",
                "pnl_pct": -0.005,
                "reasons": ["No hybrid sell criteria triggered"],
            },
        ],
    }

    text = build_sell_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/789",
        provider="kis",
        include_actions=("SELL", "REVIEW"),
    )

    assert "대상: 0건 (매도 0, 점검 0, 보유 2 제외)" in text
    assert "매도/점검 대상 없음" in text


@pytest.mark.parametrize(
    "pnl_pct",
    [float("nan"), float("inf"), "-inf", True, False],
)
def test_build_sell_telegram_report_text_treats_invalid_pnl_as_missing(
    pnl_pct: object,
) -> None:
    report = {
        "generated_at": "2026-02-11 21:00 KST",
        "summary": {
            "evaluated_count": 1,
            "issue_count": 0,
            "action_counts": {"REVIEW": 1},
        },
        "evaluated": [
            {
                "ticker": "AAPL.NAS",
                "action": "REVIEW",
                "pnl_pct": pnl_pct,
                "reasons": ["Needs manual review"],
            }
        ],
    }

    text = build_sell_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/789",
        provider="kis",
        include_actions=("REVIEW",),
    )

    assert "AAPL.NAS | 점검 | - | Needs manual review" in text


def test_build_scan_telegram_report_text_keeps_all_ready_candidates() -> None:
    candidates = []
    for idx in range(7):
        candidates.append(
            {
                "ticker": f"T{idx:03d}",
                "name": f"Name{idx}",
                "price": f"${100 + idx}",
                "score": "6.0",
                "entry_state": "READY",
                "entry_state_reason": f"Reason {idx}",
            }
        )

    report = {
        "generated_at": "2026-02-11 21:03 KST",
        "summary": {"candidate_count": 7, "issue_count": 0},
        "candidates": candidates,
    }

    text = build_scan_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/987",
        provider="kis",
        universe="US",
        max_items=5,
    )

    assert "진입 가능: 7건" in text
    assert "외 " not in text
    assert "T004 Name4" in text
    assert "T005 Name5" in text
    assert "T006 Name6" in text


def test_build_sell_telegram_report_text_limits_items_and_adds_rest_count() -> None:
    evaluated = []
    for idx in range(7):
        evaluated.append(
            {
                "ticker": f"S{idx:03d}",
                "action": "SELL" if idx % 2 == 0 else "REVIEW",
                "pnl_pct": 0.01 * (idx + 1),
                "reasons": [f"Reason {idx}"],
            }
        )

    report = {
        "generated_at": "2026-02-11 21:00 KST",
        "summary": {
            "evaluated_count": 7,
            "issue_count": 0,
            "action_counts": {"SELL": 4, "REVIEW": 3, "HOLD": 0},
        },
        "evaluated": evaluated,
    }

    text = build_sell_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/654",
        provider="kis",
        include_actions=("SELL", "REVIEW"),
        max_items=5,
    )

    assert "대상: 7건 (매도 4, 점검 3, 보유 0 제외)" in text
    assert "외 2건" in text
    assert "S004 | 매도 | +5.0% | Reason 4" in text
    assert "S005 | 점검 | +6.0% | Reason 5" not in text


def test_build_scan_slack_summary_text_keeps_key_value_format() -> None:
    report = {
        "generated_at": "2026-02-11 21:03 KST",
        "summary": {"candidate_count": 3, "issue_count": 1},
        "candidates": [{}, {}, {}],
    }

    text = build_scan_slack_summary_text(
        report=report,
        repo="mocha/swing-trading-report",
        run_url="https://github.com/mocha/swing-trading-report/actions/runs/123",
        provider="kis",
        universe="both",
        storage_key="2026/02/2026-02-11.buy.json",
    )

    assert text.splitlines() == [
        "[SAB][scan][schedule]",
        "repo=mocha/swing-trading-report",
        "provider=kis",
        "universe=both",
        "generated_at=2026-02-11 21:03 KST",
        "candidate_count=3",
        "issue_count=1",
        "storage_key=2026/02/2026-02-11.buy.json",
        "run_url=https://github.com/mocha/swing-trading-report/actions/runs/123",
    ]


def test_build_sell_slack_summary_text_keeps_key_value_format() -> None:
    report = {
        "generated_at": "2026-02-11 21:00 KST",
        "summary": {
            "evaluated_count": 4,
            "issue_count": 1,
            "action_counts": {"REVIEW": 2, "SELL": 1, "HOLD": 1},
        },
        "evaluated": [{}, {}, {}, {}],
    }

    text = build_sell_slack_summary_text(
        report=report,
        repo="mocha/swing-trading-report",
        run_url="https://github.com/mocha/swing-trading-report/actions/runs/456",
        provider="kis",
        storage_key="2026/02/2026-02-11.sell.json",
    )

    assert text.splitlines() == [
        "[SAB][sell][schedule]",
        "repo=mocha/swing-trading-report",
        "provider=kis",
        "generated_at=2026-02-11 21:00 KST",
        "evaluated_count=4",
        "issue_count=1",
        "action_counts=HOLD:1, REVIEW:2, SELL:1",
        "storage_key=2026/02/2026-02-11.sell.json",
        "run_url=https://github.com/mocha/swing-trading-report/actions/runs/456",
    ]


def test_build_ai_brief_telegram_report_text_includes_recommendations() -> None:
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt-test",
        "summary": {
            "preselected_count": 2,
            "recommendation_count": 2,
            "source_issue_count": 0,
            "system_issue_count": 0,
        },
        "recommendations": [
            {
                "ticker": "AAPL.NAS",
                "name": "Apple",
                "confidence": "HIGH",
                "rationale": ["source-backed context supports manual review"],
                "sources": [
                    {
                        "title": "Apple supply chain update",
                        "url": "https://example.test/aapl",
                        "published_at": "2026-05-05T07:00:00+09:00",
                    }
                ],
            },
            {
                "ticker": "MSFT.NAS",
                "confidence": "MEDIUM",
                "rationale": ["entry setup remains valid"],
                "sources": [
                    {
                        "title": "Microsoft product update",
                        "url": "https://example.test/msft",
                        "published_at": "2026-05-05T07:10:00+09:00",
                    }
                ],
            },
        ],
        "source_issues": [],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/789",
        max_items=5,
    )

    assert "<b>SAB AI Brief</b>" in text
    assert "시장 <code>US</code>" in text
    assert "모델 <code>openai/gpt-test</code>" in text
    assert "상태 <code>FINAL_JUDGMENT</code>" in text
    assert "사유 <code>source_backed_final</code>" in text
    assert "뉴스 근거 확인된 추천 후보 2건" in text
    assert "<b>추천 후보 2건</b> (표시 <code>2</code>건)" in text
    assert "source <code>0</code> · system <code>0</code>" in text
    assert "1. <b>AAPL.NAS Apple</b> · <code>HIGH</code>" in text
    assert "source-backed context supports manual review" in text
    assert "근거 <code>1</code>개 · Apple supply chain update" in text
    assert "2. <b>MSFT.NAS</b> · <code>MEDIUM</code>" in text
    assert "entry setup remains valid" in text


def test_build_ai_brief_telegram_report_text_uses_html_rich_text() -> None:
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt-test",
        "summary": {
            "preselected_count": 2,
            "recommendation_count": 1,
            "source_issue_count": 0,
            "system_issue_count": 0,
        },
        "recommendations": [
            {
                "ticker": "AAPL.NAS",
                "name": "Apple",
                "confidence": "HIGH",
                "rationale": ["source-backed context supports manual review"],
                "sources": [{"title": "Apple supply chain update"}],
            }
        ],
        "source_issues": [],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/789",
        storage_key="2026/05/2026-05-05.ai-brief.json",
    )

    assert text.startswith("<b>SAB AI Brief</b>")
    assert "시장 <code>US</code>" in text
    assert "모델 <code>openai/gpt-test</code>" in text
    assert "<b>판단</b>" in text
    assert "상태 <code>FINAL_JUDGMENT</code>" in text
    assert "사유 <code>source_backed_final</code>" in text
    assert "뉴스 근거 확인된 추천 후보 1건" in text
    assert "<b>추천 후보 1건</b> (표시 <code>1</code>건)" in text
    assert "1. <b>AAPL.NAS Apple</b> · <code>HIGH</code>" in text
    assert "근거 <code>1</code>개 · Apple supply chain update" in text
    assert "<b>진단</b>" in text
    assert "source <code>0</code> · system <code>0</code>" in text
    assert "보관 <code>2026/05/2026-05-05.ai-brief.json</code>" in text
    assert (
        '<a href="https://github.com/example/repo/actions/runs/789">실행 보기</a>'
        in text
    )


def test_build_ai_brief_telegram_report_text_escapes_html_values() -> None:
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt<&test>",
        "summary": {
            "preselected_count": 1,
            "recommendation_count": 1,
            "source_issue_count": 1,
            "system_issue_count": 0,
        },
        "recommendations": [
            {
                "ticker": "AAPL.NAS",
                "name": 'AT&T <Alpha "A">',
                "confidence": "HIGH",
                "rationale": ['2 < 3 & "quoted"'],
                "sources": [{"title": "News <b>bold</b> & supply"}],
            }
        ],
        "source_issues": [
            {
                "ticker": "AAPL.NAS",
                "code": "source_coverage_below_threshold",
                "message": 'bad <tag> & "quoted"',
            }
        ],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/789?x=1&y=2",
    )

    assert "모델 <code>openai/gpt&lt;&amp;test&gt;</code>" in text
    assert "<b>AAPL.NAS AT&amp;T &lt;Alpha &quot;A&quot;&gt;</b>" in text
    assert "2 &lt; 3 &amp; &quot;quoted&quot;" in text
    assert "News &lt;b&gt;bold&lt;/b&gt; &amp; supply" in text
    assert "bad &lt;tag&gt; &amp; &quot;quoted&quot;" in text
    assert (
        '<a href="https://github.com/example/repo/actions/runs/789?x=1&amp;y=2">'
        "실행 보기</a>"
    ) in text


def test_build_ai_brief_telegram_report_text_bounds_long_html_fields() -> None:
    very_long_model = "model-" + ("M" * 5000)
    very_long_ticker = "TICKER" + ("T" * 5000)
    very_long_name = "Name " + ("N" * 5000)
    very_long_rationale = "rationale " + ("R" * 5000)
    very_long_title = "source title " + ("S" * 5000)
    very_long_issue = "issue message " + ("I" * 5000)
    very_long_storage_key = "reports/" + ("K" * 5000) + ".ai-brief.json"
    unsafe_run_url = "javascript:alert(" + ("U" * 5000) + ")"
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": very_long_model,
        "summary": {
            "preselected_count": 1,
            "recommendation_count": 1,
            "source_issue_count": 1,
            "system_issue_count": 0,
        },
        "recommendations": [
            {
                "ticker": very_long_ticker,
                "name": very_long_name,
                "confidence": "HIGH",
                "rationale": [very_long_rationale],
                "sources": [{"title": very_long_title}],
            }
        ],
        "source_issues": [
            {
                "ticker": very_long_ticker,
                "code": "source_coverage_below_threshold",
                "message": very_long_issue,
            }
        ],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url=unsafe_run_url,
        storage_key=very_long_storage_key,
    )
    parts = notification_text.split_telegram_message_text(text)

    assert text.count("...") >= 7
    assert all(
        len(line) < notification_text.TELEGRAM_MESSAGE_MAX_CHARS
        for line in text.splitlines()
    )
    assert all(
        0 < len(part) <= notification_text.TELEGRAM_MESSAGE_MAX_CHARS for part in parts
    )
    _assert_balanced_html_tags(parts)


def test_build_ai_brief_telegram_report_text_does_not_link_too_long_run_url() -> None:
    long_run_url = "https://example.test/" + ("u" * 5000)
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "fake",
        "model_name": "fake-ai-brief-v1",
        "summary": {"recommendation_count": 0},
        "recommendations": [],
        "source_issues": [],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url=long_run_url,
    )
    parts = notification_text.split_telegram_message_text(text)

    assert "<a href=" not in text
    assert "URL too long" in text
    assert all(
        len(line) < notification_text.TELEGRAM_MESSAGE_MAX_CHARS
        for line in text.splitlines()
    )
    assert all(
        0 < len(part) <= notification_text.TELEGRAM_MESSAGE_MAX_CHARS for part in parts
    )
    _assert_balanced_html_tags(parts)


def test_build_ai_brief_telegram_report_text_keeps_unsafe_run_url_plain() -> None:
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "fake",
        "model_name": "fake-ai-brief-v1",
        "summary": {"recommendation_count": 0},
        "recommendations": [],
        "source_issues": [],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="javascript:alert(1)",
    )

    assert '<a href="javascript:alert(1)">' not in text
    assert "실행 javascript:alert(1)" in text


@pytest.mark.parametrize(
    "run_url",
    [
        "http://[",
        "https://example.test:bad/path",
        "https://example.test/a b",
        "https://example.test/\npath",
        "https://example.test/\tpath",
    ],
)
def test_build_ai_brief_telegram_report_text_keeps_malformed_http_run_url_plain(
    run_url: str,
) -> None:
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "fake",
        "model_name": "fake-ai-brief-v1",
        "summary": {"recommendation_count": 0},
        "recommendations": [],
        "source_issues": [],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(report=report, run_url=run_url)
    parts = notification_text.split_telegram_message_text(text)

    assert "<a href=" not in text
    assert "실행 " in text
    assert all(
        0 < len(part) <= notification_text.TELEGRAM_MESSAGE_MAX_CHARS for part in parts
    )
    _assert_balanced_html_tags(parts)


def test_build_ai_brief_telegram_report_text_explains_weak_news_coverage() -> None:
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt-test",
        "summary": {
            "preselected_count": 2,
            "recommendation_count": 1,
            "source_issue_count": 1,
            "system_issue_count": 0,
        },
        "eligible_tickers": ["AAPL.NAS", "MSFT.NAS"],
        "recommendations": [
            {
                "ticker": "MSFT.NAS",
                "confidence": "MEDIUM",
                "rationale": ["entry setup remains valid"],
                "sources": [],
            }
        ],
        "source_issues": [
            {
                "ticker": "MSFT.NAS",
                "code": "openai_no_external_sources",
                "severity": "WARN",
                "message": "No supplied source context.",
            }
        ],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/789",
        max_items=5,
    )

    assert "상태 <code>NEEDS_REVIEW_WEAK_NEWS</code>" in text
    assert "사유 <code>weak_news_coverage</code>" in text
    assert "뉴스 근거 약함, 기술 신호만 있음" in text
    assert "대상: AAPL.NAS, MSFT.NAS" in text
    assert (
        "source issue: MSFT.NAS openai_no_external_sources - "
        "No supplied source context."
    ) in text


def test_build_ai_brief_telegram_report_text_counts_issue_arrays_when_summary_is_stale() -> (
    None
):
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt-test",
        "summary": {
            "preselected_count": 1,
            "recommendation_count": 1,
            "source_issue_count": 0,
            "system_issue_count": 0,
        },
        "eligible_tickers": ["AAPL.NAS"],
        "recommendations": [
            {
                "ticker": "AAPL.NAS",
                "confidence": "HIGH",
                "rationale": ["entry setup remains valid"],
                "sources": [
                    {
                        "title": "Apple supply chain update",
                        "url": "https://example.test/aapl",
                        "published_at": "2026-05-05T07:00:00+09:00",
                    }
                ],
            }
        ],
        "source_issues": [
            {
                "ticker": "AAPL.NAS",
                "code": "source_coverage_below_threshold",
                "severity": "WARN",
                "message": "Source coverage was below threshold.",
            }
        ],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/789",
    )

    assert "상태 <code>NEEDS_REVIEW_WEAK_NEWS</code>" in text
    assert "사유 <code>weak_news_coverage</code>" in text
    assert "source <code>1</code> · system <code>0</code>" in text


def test_build_ai_brief_telegram_report_text_handles_zero_recommendations() -> None:
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "KR",
        "model_provider": "fake",
        "model_name": "fake-ai-brief-v1",
        "summary": {
            "preselected_count": 1,
            "recommendation_count": 0,
            "source_issue_count": 0,
            "system_issue_count": 1,
        },
        "eligible_tickers": ["005930"],
        "recommendations": [],
        "source_issues": [],
        "system_issues": [
            {
                "ticker": None,
                "code": "model_provider_timeout",
                "severity": "ERROR",
                "message": "OpenAI request timed out.",
            }
        ],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/790",
    )

    assert "추천 <code>0</code>건 · 표시 <code>0</code>건" in text
    assert "상태 <code>NEEDS_REVIEW_WEAK_NEWS</code>" in text
    assert "사유 <code>model_or_system_issue</code>" in text
    assert "AI 판단 보류: 모델/시스템 이슈 확인 필요" in text
    assert "추천 후보 없음" in text
    assert "system issue: model_provider_timeout - OpenAI request timed out." in text


def test_build_ai_brief_telegram_report_text_explains_model_failure_with_candidates() -> (
    None
):
    report = {
        "generated_at": "2026-05-20T02:19:26+00:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt-5.4-mini",
        "summary": {
            "entry_count": 3,
            "preselected_count": 3,
            "recommendation_count": 0,
            "source_issue_count": 0,
            "system_issue_count": 1,
        },
        "eligible_tickers": ["AXTI.NAS", "WELL.NYS", "BABA.NYS"],
        "recommendations": [],
        "source_issues": [],
        "system_issues": [
            {
                "ticker": None,
                "code": "model_provider_failed",
                "severity": "ERROR",
                "message": "OpenAI request failed with HTTP 429: quota exceeded",
            }
        ],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/790",
    )

    assert "추천 <code>0</code>건 · 표시 <code>0</code>건" in text
    assert "모델 입력 <code>3</code>건" in text
    assert "사유 <code>model_or_system_issue</code>" in text
    assert "AI 판단 보류: 모델/시스템 이슈 확인 필요" in text
    assert (
        "추천 생성 실패/보류: recommendable 후보 3건이 있었지만 추천 결과가 비었습니다."
        in text
    )
    assert "ENTER 후보" not in text
    assert "대상: AXTI.NAS, WELL.NYS, BABA.NYS" in text
    assert (
        "system issue: model_provider_failed - OpenAI request failed with HTTP 429: "
        "quota exceeded"
    ) in text


def test_build_ai_brief_telegram_report_text_includes_watch_and_source_chain() -> None:
    report = {
        "generated_at": "2026-05-20T02:19:26+00:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt-5.4-mini",
        "summary": {
            "recommendable_count": 7,
            "watch_count": 2,
            "preselected_count": 5,
            "recommendation_count": 0,
            "source_issue_count": 0,
            "system_issue_count": 1,
        },
        "eligible_tickers": ["AXTI.NAS", "WELL.NYS", "BABA.NYS"],
        "watch_tickers": ["AAPL.NAS", "MSFT.NAS"],
        "recommendations": [],
        "source_provider_summary": {
            "chain": ["finnhub", "benzinga-news"],
            "providers": [
                {"provider": "finnhub", "status": "success", "covered": 3, "total": 7},
                {
                    "provider": "benzinga-news",
                    "status": "success",
                    "covered": 0,
                    "total": 4,
                },
            ],
            "final": {
                "recommendable_covered": 3,
                "recommendable_total": 7,
                "watch_covered": 1,
                "watch_total": 2,
            },
        },
        "source_issues": [],
        "system_issues": [
            {
                "ticker": None,
                "code": "model_provider_failed",
                "severity": "ERROR",
                "message": "OpenAI request failed.",
            }
        ],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/790",
    )

    assert "watch 후보 <code>2</code>건: AAPL.NAS, MSFT.NAS" in text
    assert (
        "<code>source_chain=finnhub,benzinga-news final recommendable=3/7 "
        "watch=1/2</code>" in text
    )
    assert (
        "<code>source_providers=finnhub success 3/7; "
        "benzinga-news success 0/4</code>" in text
    )
    assert (
        "추천 생성 실패/보류: recommendable 후보 7건(모델 입력 5건)이 있었지만 "
        "추천 결과가 비었습니다." in text
    )
    assert "ENTER 후보" not in text


def test_build_ai_brief_telegram_report_text_explains_watch_only_state() -> None:
    report = {
        "generated_at": "2026-05-20T02:19:26+00:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt-5.4-mini",
        "summary": {
            "recommendable_count": 0,
            "watch_count": 1,
            "preselected_count": 0,
            "recommendation_count": 0,
            "source_issue_count": 0,
            "system_issue_count": 0,
        },
        "eligible_tickers": [],
        "watch_tickers": ["MSFT.NAS"],
        "watch_candidates": [
            {
                "ticker": "MSFT.NAS",
                "action": "WATCH",
                "reason": "entry trigger is pending re-confirmation",
                "retrigger_conditions": [
                    "price must satisfy the original entry trigger again"
                ],
            }
        ],
        "recommendations": [],
        "source_issues": [],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/790",
    )

    assert "상태 <code>NEEDS_REVIEW_WATCH_ONLY</code>" in text
    assert "사유 <code>watch_only_trigger_pending</code>" in text
    assert "watch 후보 <code>1</code>건: MSFT.NAS" in text
    assert "watch 후보만 있음. 재트리거 조건 확인 필요" in text
    assert "오늘은 볼 종목 없음" not in text


def test_build_ai_brief_telegram_report_text_includes_vetoed_candidates() -> None:
    report = {
        "generated_at": "2026-05-20T02:19:26+00:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt-5.4-mini",
        "summary": {
            "preselected_count": 2,
            "recommendation_count": 0,
            "vetoed_count": 1,
            "source_issue_count": 0,
            "system_issue_count": 0,
        },
        "eligible_tickers": ["AXTI.NAS", "WELL.NYS"],
        "recommendations": [],
        "vetoed_candidates": [
            {
                "ticker": "AXTI.NAS",
                "action": "SKIP",
                "reason": "earnings event risk blocks the setup",
            }
        ],
        "source_issues": [],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/790",
    )

    assert "AI 판단 제외 1건" in text
    assert (
        "<code>AXTI.NAS</code> · <code>SKIP</code> · "
        "earnings event risk blocks the setup"
    ) in text


def test_build_ai_brief_telegram_report_text_limits_eligible_ticker_preview() -> None:
    report = {
        "generated_at": "2026-05-20T02:19:26+00:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt-5.4-mini",
        "summary": {
            "preselected_count": 7,
            "recommendation_count": 0,
            "source_issue_count": 0,
            "system_issue_count": 1,
        },
        "eligible_tickers": [
            "T000.NAS",
            "T001.NAS",
            "T002.NAS",
            "T003.NAS",
            "T004.NAS",
            "T005.NAS",
            "T006.NAS",
        ],
        "recommendations": [],
        "source_issues": [],
        "system_issues": [
            {
                "ticker": None,
                "code": "model_provider_failed",
                "severity": "ERROR",
                "message": "OpenAI request failed.",
            }
        ],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/790",
    )

    assert "모델 입력 <code>7</code>건" in text
    assert "대상: T000.NAS, T001.NAS, T002.NAS, T003.NAS, T004.NAS, 외 2건" in text
    assert "T005.NAS" not in text


def test_build_ai_brief_telegram_report_text_limits_items_and_adds_rest_count() -> None:
    recommendations = []
    for idx in range(7):
        recommendations.append(
            {
                "ticker": f"T{idx:03d}.NAS",
                "name": f"Name{idx}",
                "confidence": "LOW",
                "rationale": [f"Reason {idx}"],
                "sources": [],
            }
        )
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "fake",
        "model_name": "fake-ai-brief-v1",
        "summary": {"recommendation_count": 7},
        "recommendations": recommendations,
        "source_issues": [],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/791",
        max_items=5,
    )

    assert "<b>추천 후보 7건</b> (표시 <code>3</code>건)" in text
    assert "상태 <code>NEEDS_REVIEW_WEAK_NEWS</code>" in text
    assert "사유 <code>weak_news_coverage</code>" in text
    assert "외 <code>4</code>건" in text
    assert "T002.NAS Name2" in text
    assert "T003.NAS Name3" not in text


def test_build_ai_brief_telegram_report_text_includes_storage_key() -> None:
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "fake",
        "model_name": "fake-ai-brief-v1",
        "summary": {"recommendation_count": 0},
        "recommendations": [],
        "source_issues": [],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/792",
        storage_key="2026/05/2026-05-05.ai-brief.json",
    )

    assert "보관 <code>2026/05/2026-05-05.ai-brief.json</code>" in text
    assert "오늘은 볼 종목 없음. 쉬어도 됨" in text
    assert text.endswith(
        '<a href="https://github.com/example/repo/actions/runs/792">실행 보기</a>'
    )


def test_build_ai_brief_slack_summary_text_keeps_key_value_format() -> None:
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt-test",
        "summary": {
            "preselected_count": 5,
            "recommendation_count": 3,
            "vetoed_count": 0,
            "source_issue_count": 1,
            "system_issue_count": 0,
        },
        "recommendations": [{}, {}, {}],
        "source_issues": [{}],
        "system_issues": [],
    }

    text = build_ai_brief_slack_summary_text(
        report=report,
        repo="mocha/swing-trading-report",
        run_url="https://github.com/mocha/swing-trading-report/actions/runs/789",
        storage_key="2026/05/2026-05-05.ai-brief.json",
    )

    assert text.splitlines() == [
        "[SAB][ai-brief][schedule]",
        "repo=mocha/swing-trading-report",
        "market=US",
        "model_provider=openai",
        "model_name=gpt-test",
        "generated_at=2026-05-05T08:40:00+09:00",
        "brief_state=NEEDS_REVIEW_WEAK_NEWS",
        "brief_reason=weak_news_coverage",
        "preselected_count=5",
        "recommendation_count=3",
        "vetoed_count=0",
        "source_issue_count=1",
        "system_issue_count=0",
        "storage_key=2026/05/2026-05-05.ai-brief.json",
        "run_url=https://github.com/mocha/swing-trading-report/actions/runs/789",
    ]


def test_build_ai_brief_slack_summary_text_falls_back_to_top_level_counts() -> None:
    report = {
        "date": "2026-05-05",
        "market": "KR",
        "preselected_count": "4",
        "recommendation_count": "2",
        "vetoed_count": "0",
        "source_issue_count": "1",
        "system_issue_count": "3",
        "recommendations": [],
        "source_issues": [],
        "system_issues": [],
    }

    text = build_ai_brief_slack_summary_text(
        report=report,
        repo="mocha/swing-trading-report",
        run_url="https://github.com/mocha/swing-trading-report/actions/runs/793",
    )

    assert text.splitlines() == [
        "[SAB][ai-brief][schedule]",
        "repo=mocha/swing-trading-report",
        "market=KR",
        "model_provider=fake",
        "model_name=-",
        "generated_at=2026-05-05",
        "brief_state=NEEDS_REVIEW_WEAK_NEWS",
        "brief_reason=model_or_system_issue",
        "preselected_count=4",
        "recommendation_count=2",
        "vetoed_count=0",
        "source_issue_count=1",
        "system_issue_count=3",
        "run_url=https://github.com/mocha/swing-trading-report/actions/runs/793",
    ]


def test_build_ai_brief_slack_summary_text_counts_vetoed_candidates() -> None:
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt-test",
        "summary": {
            "preselected_count": 1,
            "recommendation_count": 0,
            "vetoed_count": 1,
            "source_issue_count": 0,
            "system_issue_count": 0,
        },
        "eligible_tickers": ["AAPL.NAS"],
        "recommendations": [],
        "vetoed_candidates": [
            {
                "ticker": "AAPL.NAS",
                "action": "SKIP",
                "reason": "headline risk",
            }
        ],
        "source_issues": [],
        "system_issues": [],
    }

    text = build_ai_brief_slack_summary_text(
        report=report,
        repo="mocha/swing-trading-report",
        run_url="https://github.com/mocha/swing-trading-report/actions/runs/793",
    )

    assert "vetoed_count=1" in text


def test_build_ai_brief_slack_summary_text_includes_watch_and_source_chain() -> None:
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt-test",
        "summary": {
            "recommendable_count": 7,
            "watch_count": 2,
            "preselected_count": 5,
            "recommendation_count": 3,
            "vetoed_count": 0,
            "source_issue_count": 1,
            "system_issue_count": 0,
        },
        "watch_tickers": ["AAPL.NAS", "MSFT.NAS"],
        "recommendations": [{}, {}, {}],
        "source_provider_summary": {
            "chain": ["finnhub", "benzinga-news"],
            "providers": [
                {"provider": "finnhub", "status": "success", "covered": 3, "total": 7},
                {
                    "provider": "benzinga-news",
                    "status": "success",
                    "covered": 0,
                    "total": 4,
                },
            ],
            "final": {
                "recommendable_covered": 3,
                "recommendable_total": 7,
                "watch_covered": 1,
                "watch_total": 2,
            },
        },
        "source_issues": [{}],
        "system_issues": [],
    }

    text = build_ai_brief_slack_summary_text(
        report=report,
        repo="mocha/swing-trading-report",
        run_url="https://github.com/mocha/swing-trading-report/actions/runs/789",
    )

    assert "watch_count=2" in text
    assert "watch_tickers=AAPL.NAS, MSFT.NAS" in text
    assert "source_chain=finnhub,benzinga-news" in text
    assert "source_final_recommendable=3/7" in text
    assert "source_final_watch=1/2" in text
    assert "source_providers=finnhub success 3/7; benzinga-news success 0/4" in text


def test_build_ai_brief_skipped_telegram_text_explains_delayed_preopen() -> None:
    text = build_ai_brief_skipped_telegram_text(
        market="US",
        session_state="INTRADAY",
        session_date="2026-05-22",
        expected_state="PRE_OPEN",
        local_time="2026-05-22T09:33:17-04:00",
        trading_session="true",
        run_url="https://github.com/example/repo/actions/runs/800",
    )

    assert "[SAB][ai-brief][skipped]" in text
    assert "market=US" in text
    assert "session_state=INTRADAY" in text
    assert "expected_state=PRE_OPEN" in text
    assert "session_date=2026-05-22" in text
    assert "local_time=2026-05-22T09:33:17-04:00" in text
    assert "trading_session=true" in text
    assert "GitHub scheduled run이 장전 window 이후 실행되어 AI Brief 건너뜀" in text
    assert "reason=scheduled_run_after_pre_open_window" in text
    assert text.endswith("run_url=https://github.com/example/repo/actions/runs/800")


def test_build_ai_brief_skipped_telegram_text_explains_wrong_session_state() -> None:
    text = build_ai_brief_skipped_telegram_text(
        market="US",
        session_state="AFTER_CLOSE",
        session_date="2026-05-22",
        expected_state="PRE_OPEN",
        trading_session="true",
        run_url="https://github.com/example/repo/actions/runs/802",
    )

    assert "trading_session=true" in text
    assert "장전 시간이 아니라 AI Brief 건너뜀" in text
    assert "reason=scheduled_run_after_pre_open_window" not in text


def test_build_ai_brief_skipped_telegram_text_explains_non_trading_session() -> None:
    text = build_ai_brief_skipped_telegram_text(
        market="US",
        session_state="AFTER_CLOSE",
        session_date="2026-05-25",
        trading_session="false",
        run_url="https://github.com/example/repo/actions/runs/801",
    )

    assert "trading_session=false" in text
    assert "거래일이 아니라 AI Brief 건너뜀" in text
    assert "장전 시간이 아니라 AI Brief 건너뜀" not in text
