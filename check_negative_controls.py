"""Run the same behavior checks against isolated, deliberately broken copies."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTROLS = [
    (
        "binary32_representation",
        '        return struct.unpack("!f", struct.pack("!f", float(original)))[0] == float(\n            reference\n        )',
        "        return False",
        "test_binary32_reference_preserves_cent_boundary_prices_without_tolerance",
    ),
    (
        "binary32_not_generic_tolerance",
        '        return struct.unpack("!f", struct.pack("!f", float(original)))[0] == float(\n            reference\n        )',
        "        return True",
        "test_binary32_reference_preserves_cent_boundary_prices_without_tolerance",
    ),
    (
        "binary32_precision_limit",
        '    if abs(original - reference) >= Decimal(".005")',
        "    if False",
        "test_binary32_reference_preserves_cent_boundary_prices_without_tolerance",
    ),
    (
        "calendar_rate_limit",
        "            time.sleep(0.3",
        "            time.sleep(0.1",
        "test_calendar_collection_respects_three_requests_per_second",
    ),
    (
        "held_quote_validation",
        '    if not all(key in inputs for key in ("stock", "calendar", "bars_0"))',
        "    if held",
        "test_live_session_hold_does_not_hide_invalid_quotes",
    ),
    (
        "breakout_equality",
        '            "close_not_above_breakout": last["clos"] >',
        '            "close_not_above_breakout": last["clos"] >=',
        "test_breakout_equality_is_excluded",
    ),
    (
        "volume_boundary",
        '            "volume_below_multiple": last["tvol"]\n            >= avg_volume * Decimal(RULES["volume_multiple"]',
        '            "volume_below_multiple": last["tvol"] >= avg_volume * Decimal("1.4"',
        "test_volume_multiple_below_boundary_is_excluded",
    ),
    (
        "market_cap_boundary",
        '            "market_cap_below_minimum": cap >= Decimal(RULES["market_cap_min_usd"]',
        '            "market_cap_below_minimum": cap >= Decimal("9000000000"',
        "test_market_cap_below_boundary_is_excluded",
    ),
    (
        "liquidity_boundary",
        "        if turnover <",
        "        if turnover <=",
        "test_turnover_inclusive_boundary",
    ),
    (
        "sma_equality",
        '            "close_not_above_sma50": last["clos"] >',
        '            "close_not_above_sma50": last["clos"] >=',
        "test_sma_equality_is_excluded",
    ),
    (
        "bad_quotes",
        '                raise DataError("invalid_ohlc")',
        "                pass",
        "test_bad_quotes_are_held_without_a_price_plan",
    ),
    (
        "estimated_earnings",
        '            return {\n                "status": "unconfirmed",\n                "source": url,\n                "reason": "uncertain_earnings_announcement",\n            }',
        "            pass",
        "test_unconfirmed_and_estimated_earnings_are_held",
    ),
    (
        "newer_earnings_change",
        '    return (\n        max(newer_changes, key=lambda item: timestamp(item["published_at"]))\n        if newer_changes\n        else next_event\n    )',
        "    return next_event",
        "test_newer_earnings_postponement_invalidates_original_announcement",
    ),
    (
        "missing_earnings",
        '    if inputs["earnings"].get("status") != "confirmed"',
        "    if False",
        "test_unconfirmed_and_estimated_earnings_are_held",
    ),
    (
        "earnings_fifth_session",
        "            if not (event >",
        "            if not (event >=",
        "test_earnings_window_includes_today_fifth_session_and_weekend",
    ),
    (
        "wrong_target",
        '            "target": entry + risk * 2',
        '            "target": entry + risk * 3',
        "test_selected_report_and_offline_replay",
    ),
    (
        "unverified_live_data",
        "    if any(meta.get(key) != value for key, value in required.items())",
        "    if False",
        "test_unverified_live_session_cannot_become_candidate",
    ),
    (
        "reference_price",
        '                    raise DataError("daily_price_reference_mismatch")',
        "                    pass",
        "test_reference_disagreement_or_unknown_adjustment_is_held",
    ),
    (
        "reference_volume",
        '                    raise DataError("invalid_daily_volume_units")',
        "                    pass",
        "test_reference_disagreement_or_unknown_adjustment_is_held",
    ),
    (
        "corporate_action_metadata",
        '        raise DataError("corporate_action_metadata_invalid")',
        "        pass",
        "test_reference_disagreement_or_unknown_adjustment_is_held",
    ),
    (
        "split_window",
        '        if reference["events"].get("splits")',
        "        if False",
        "test_split_window_is_held",
    ),
    (
        "report_day_split",
        "    end = datetime.combine(report_day + timedelta(days=1)",
        "    end = datetime.combine(report_day",
        "test_report_day_split_is_checked_before_publishing_prices",
    ),
    (
        "dividend_policy",
        '        if reference["events"].get("splits")',
        '        if reference["events"].get("splits") or reference["events"].get("dividends")',
        "test_cash_dividend_keeps_the_unadjusted_price_plan",
    ),
    (
        "amount_rounding",
        "            found[moment] = max(Decimal(0), amount - 1)",
        "            found[moment] = amount",
        "test_turnover_inclusive_boundary",
    ),
    (
        "insufficient_bound",
        '            raise DataError("turnover_lower_bound_insufficient")',
        '            return result | {"status": "excluded"}',
        "test_turnover_inclusive_boundary",
    ),
    (
        "missing_minutes",
        "    if set(found) != set(expected)",
        "    if False",
        "test_invalid_regular_turnover_is_held",
    ),
    (
        "duplicate_minutes",
        '                raise DataError("duplicate_or_unordered_minutes")',
        "                pass",
        "test_invalid_regular_turnover_is_held",
    ),
    (
        "minute_amount_units",
        '                raise DataError("turnover_unit_or_session_mismatch")',
        "                pass",
        "test_invalid_regular_turnover_is_held",
    ),
    (
        "minute_timezone",
        '                raise DataError("minute_timezone_mismatch")',
        "                pass",
        "test_invalid_regular_turnover_is_held",
    ),
]

UNIVERSE_CONTROLS = [
    (
        "non_common_detail_identity",
        '                        or row.get("isinCode") != evidence["isin"]\n                        or row.get("',
        '                        or row.get("',
        "test_non_common_review_cannot_hide_missing_identity_evidence_or_other_listings",
    ),
    (
        "non_common_listing_identity",
        '                        or any(\n                            entry.get("symbol") != symbol\n                            or entry.get("isinCode") != evidence["isin"]\n                            for entry in listing_rows\n                        ',
        "                        or any(False for entry in listing_rows",
        "test_non_common_review_cannot_hide_missing_identity_evidence_or_other_listings",
    ),
    (
        "non_common_pdf_digest",
        '                        if (\n                            hashlib.sha256(body.encode()).hexdigest()\n                            != evidence["required_body_sha256"]\n                        ):',
        "                        if False:",
        "test_reviewed_pdf_requires_exact_bytes_and_replays_without_network",
    ),
    (
        "non_common_evidence",
        '                        if not all(\n                            fragment in text for fragment in evidence["required_text"]\n                        )',
        "                        if False",
        "test_non_common_review_cannot_hide_missing_identity_evidence_or_other_listings",
    ),
    (
        "non_common_review_date",
        '                    if (\n                        date.fromisoformat(evidence["reviewed_on"])\n                        > as_of.astimezone(s.NY).date()\n                    ):',
        "                    if False:",
        "test_non_common_review_cannot_hide_missing_identity_evidence_or_other_listings",
    ),
    (
        "non_common_coverage",
        '            and set(listing["conflicts"]) <= ',
        "            and ",
        "test_non_common_review_cannot_hide_missing_identity_evidence_or_other_listings",
    ),
    (
        "non_common_exclusion",
        "                if classification",
        "                if False",
        "test_reviewed_non_common_security_resolves_only_its_listing_conflict",
    ),
    (
        "non_common_is_not_price_evaluation",
        "        if evaluated_exclusion",
        '        if counts["excluded"]',
        "test_reviewed_non_common_security_resolves_only_its_listing_conflict",
    ),
    (
        "listing_conflict_candidate",
        '            elif symbol in universe["markets"][item["market"]]["conflicts"]',
        "            elif False",
        "test_listing_conflicts_are_preserved_per_symbol_for_reconciliation",
    ),
    (
        "malformed_listing",
        '                        or not isinstance(row["securityType"], str)\n                        or ',
        "                        or ",
        "test_malformed_listing_preserves_verified_partition_and_record",
    ),
    (
        "list_omission",
        '        if not lists[""] or filtered != partitioned',
        "        if False",
        "test_missing_list_entries_never_claim_complete_coverage",
    ),
    (
        "partial_results",
        '        "candidates": ',
        '        "candidates": [] if counts["held"] else ',
        "test_partial_hold_keeps_verified_candidate_and_replays",
    ),
    (
        "top_three_limit",
        '        "candidates": candidates[:3',
        '        "candidates": candidates[:4',
        "test_top_three_use_automatically_collected_company_announcements",
    ),
    (
        "volume_ranking",
        "            -",
        "            ",
        "test_top_three_use_automatically_collected_company_announcements",
    ),
    (
        "unverified_tie",
        '        if ratios[Decimal(stocks[symbol]["result"]["metrics"]["volume_ratio"])] > 1',
        '        if ratios[Decimal(stocks[symbol]["result"]["metrics"]["volume_ratio"])] > 100',
        "test_equal_volume_ratios_do_not_rank_by_turnover_lower_bounds",
    ),
    (
        "ranking_input_preservation",
        '    stocks = dict(inputs["stocks"])',
        '    stocks = inputs["stocks"]',
        "test_ranking_preserves_collected_inputs_and_repeats_final_decisions",
    ),
    (
        "no_candidates_vs_held",
        '        "status": "selected"\n        if candidates\n        else "excluded"\n        if evaluated_exclusion\n       ',
        '        "status": "selected" if candidates',
        "test_verified_no_candidates_and_all_held_are_distinct",
    ),
]


RECORD_CONTROLS = [
    (
        "replay_report",
        '            raise DataError("replay_report_mismatch")',
        "            pass",
        "test_universe_run.UniverseRunTests.test_replay_rejects_modified_input_and_report_and_never_fetches",
    ),
    (
        "replay_record",
        '            raise DataError("record_integrity_mismatch")',
        "            pass",
        "test_universe_run.UniverseRunTests.test_replay_rejects_modified_input_and_report_and_never_fetches",
    ),
    (
        "replay_contract",
        '        "contract": contract.read_text()',
        '        "contract": ""',
        "test_execution_record.ExecutionRecordTests.test_both_replays_reject_changed_contract",
    ),
    (
        "replay_shared_code",
        "    return {\n        path.name: hashlib.sha256(path.read_bytes()).hexdigest()\n        for path in (*paths, Path(__file__))\n    ",
        "    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths",
        "test_execution_record.ExecutionRecordTests.test_v2_records_include_shared_code_and_reject_its_changes",
    ),
    (
        "replay_identity",
        "        if any(record.get(key) != value for key, value in expected.items())",
        "        if False",
        "test_execution_record.ExecutionRecordTests.test_replays_reject_changed_rules_and_format",
    ),
    (
        "replay_response_order",
        '            if item is None or item["url"] != url',
        "            if item is None",
        "test_execution_record.ExecutionRecordTests.test_replays_reject_response_sequence_changes",
    ),
    (
        "replay_response_missing",
        "        if self._replay_failure:\n            r",
        "        if False:\n            r",
        "test_execution_record.ExecutionRecordTests.test_replays_reject_response_sequence_changes",
    ),
    (
        "replay_remaining",
        '        if (\n            next(self._remaining, None) is not None\n            or inputs != self.record["inputs"]\n            or result != self.record["result"]\n        )',
        '        if inputs != self.record["inputs"] or result != self.record["result"]',
        "test_execution_record.ExecutionRecordTests.test_replays_reject_response_sequence_changes",
    ),
    (
        "replay_inputs",
        '            or inputs != self.record["inputs"]',
        "            or False",
        "test_execution_record.ExecutionRecordTests.test_replays_reject_rechecksummed_inputs_and_results",
    ),
    (
        "replay_results",
        '            or result != self.record["result"]',
        "            or False",
        "test_execution_record.ExecutionRecordTests.test_replays_reject_rechecksummed_inputs_and_results",
    ),
]


def main() -> int:
    results = []
    cases = [
        ("single_run.py", "test_single_run.SingleRunTests", control)
        for control in CONTROLS
    ]
    cases += [
        ("universe_run.py", "test_universe_run.UniverseRunTests", control)
        for control in UNIVERSE_CONTROLS
    ]
    cases += [
        ("single_run.py", "test_single_run.SingleRunTests", control)
        for control in [
            (
                "atr_simple_average",
                "        atr = sum(tr[:14]) / 14\n        for value in tr[14:]:\n            atr = (atr * 13 + value) / 14",
                "        atr = sum(tr[-14:]) / 14",
                "test_atr_wilder_seed_and_both_gap_directions",
            ),
            (
                "atr_upward_gap",
                '                abs(row["high"] - previous["clos"]),',
                "                Decimal(0),",
                "test_atr_wilder_seed_and_both_gap_directions",
            ),
            (
                "atr_downward_gap",
                '                abs(row["low"] - previous["clos"]),',
                "                Decimal(0),",
                "test_atr_wilder_seed_and_both_gap_directions",
            ),
            (
                "sma20_instead_of_50",
                '        sma = sum(row["clos"] for row in series) / 50',
                '        sma = sum(row["clos"] for row in series[-20:]) / 20',
                "test_sma50_includes_the_oldest_close",
            ),
            (
                "sma49_instead_of_50",
                '        sma = sum(row["clos"] for row in series) / 50',
                '        sma = sum(row["clos"] for row in series[-49:]) / 49',
                "test_sma50_includes_the_oldest_close",
            ),
            (
                "breakout_19_sessions",
                '        base = max(row["high"] for row in series[-21:-1])',
                '        base = max(row["high"] for row in series[-20:-1])',
                "test_breakout_window_includes_twentieth_but_not_twenty_first_prior_bar",
            ),
            (
                "breakout_21_sessions",
                '        base = max(row["high"] for row in series[-21:-1])',
                '        base = max(row["high"] for row in series[-22:-1])',
                "test_breakout_window_includes_twentieth_but_not_twenty_first_prior_bar",
            ),
            (
                "volume_19_sessions",
                '        avg_volume = sum(row["tvol"] for row in series[-21:-1]) / 20',
                '        avg_volume = sum(row["tvol"] for row in series[-20:-1]) / 19',
                "test_volume_window_includes_twentieth_but_not_twenty_first_prior_bar",
            ),
            (
                "volume_21_sessions",
                '        avg_volume = sum(row["tvol"] for row in series[-21:-1]) / 20',
                '        avg_volume = sum(row["tvol"] for row in series[-22:-1]) / 21',
                "test_volume_window_includes_twentieth_but_not_twenty_first_prior_bar",
            ),
            (
                "kis_duplicate_or_order_guard",
                '        if len(days) != len(set(days)) or days != sorted(days, reverse=True):\n            raise DataError("duplicate_or_unordered_bars")',
                "        pass",
                "test_stale_missing_duplicate_and_future_quotes_are_held",
            ),
            (
                "kis_session_window_guard",
                '        if days[:50] != list(reversed(expected)):\n            raise DataError("missing_stale_or_future_bars")',
                "        pass",
                "test_stale_missing_duplicate_and_future_quotes_are_held",
            ),
        ]
    ]
    cases += [
        ("single_run.py", "test_universe_run.UniverseRunTests", control)
        for control in [
            (
                "nyse_daily_exchange",
                '"EXCD": exchange,\n                    "SYMB": symbol,\n                    "GUBN": "0",',
                '"EXCD": "NAS",\n                    "SYMB": symbol,\n                    "GUBN": "0",',
                "test_nyse_candidate_uses_nys_for_daily_and_intraday_prices",
            ),
            (
                "nyse_intraday_exchange",
                '"EXCD": exchange,\n                    "SYMB": symbol,\n                    "NMIN": "30",',
                '"EXCD": "NAS",\n                    "SYMB": symbol,\n                    "NMIN": "30",',
                "test_nyse_candidate_uses_nys_for_daily_and_intraday_prices",
            ),
        ]
    ]
    cases += [
        ("universe_run.py", "test_universe_run.UniverseRunTests", control)
        for control in [
            (
                "foreign_stock_partition",
                '            for kind in RULES["types"]\n            for symbol, row in lists[kind].items()',
                '            for kind in ("STOCK",)\n            for symbol, row in lists[kind].items()',
                "test_foreign_common_stock_reconciles_and_is_selected",
            ),
            (
                "stock_detail_batch_limit",
                "    for start in range(0, len(symbols), 200):\n        batch = symbols[start : start + 200]",
                "    for start in range(0, len(symbols), 2000):\n        batch = symbols[start : start + 2000]",
                "test_stock_detail_batches_cover_201_symbols_once",
            ),
        ]
    ]
    cases.append(
        (
            "probe_alpaca_trades.py",
            "test_probe_alpaca_trades.ProbeTests",
            (
                "credential_echo_guard",
                '                if key in body or secret in body:\n                    raise ValueError("credential_echo_rejected")',
                "                pass",
                "test_credential_echo_is_rejected_without_saving_or_exposing_it",
            ),
        )
    )
    for filename, signature, call, error in (
        (
            "single_run.py",
            "def replay(output: Path) -> dict:",
            'run.__kwdefaults__["fetch"](NEWS, credentials={})',
            "DataError",
        ),
        (
            "universe_run.py",
            "def replay(output):",
            'run.__kwdefaults__["fetch"](s.NEWS, credentials={})',
            "s.DataError",
        ),
    ):
        for test in (
            "test_both_replays_succeed_without_network",
            "test_both_replays_reject_record_and_report_changes_without_network",
        ):
            cases.append(
                (
                    filename,
                    "test_execution_record.ExecutionRecordTests",
                    (
                        filename + "_" + test + "_bound_network",
                        signature,
                        signature
                        + f"\n    try:\n        {call}\n    except ({error}, AssertionError):\n        pass",
                        test,
                    ),
                )
            )
    cases.append(
        (
            "execution_record.py",
            "test_execution_record.ExecutionRecordTests",
            (
                "replay_direct_socket",
                "    def verify(self, inputs, result, render):",
                '    def verify(self, inputs, result, render):\n        import socket\n        try:\n            with socket.socket() as connection:\n                connection.connect(("127.0.0.1", 1))\n        except AssertionError:\n            pass',
                "test_both_replays_succeed_without_network",
            ),
        )
    )
    cases += [
        ("probe_earnings_sources.py", "test_universe_run.UniverseRunTests", control)
        for control in [
            (
                "ir_probe_live_error",
                '        if args.production and entry["status"] != 200',
                "        if False",
                "test_production_ir_probe_preserves_page_split_errors_and_replays",
            ),
            (
                "ir_probe_replay_error",
                '            if record.get("production") and entry["status"] != 200',
                "            if False",
                "test_production_ir_probe_preserves_page_split_errors_and_replays",
            ),
        ]
    ]
    cases += [
        ("single_run.py", "test_universe_run.UniverseRunTests", control)
        for control in [
            (
                "ir_past_conflict",
                "        if not parsed_dates or max(parsed_dates) < report_day",
                "        if not parsed_dates",
                "test_repligen_archive_ignores_only_wholly_past_date_conflicts",
            ),
            (
                "ir_mixed_conflict",
                "        if not parsed_dates or max",
                "        if not parsed_dates or min",
                "test_repligen_archive_ignores_only_wholly_past_date_conflicts",
            ),
            (
                "pdf_transport",
                '            if body.startswith(b"%PDF-")',
                "            if False",
                "test_reviewed_pdf_requires_exact_bytes_and_replays_without_network",
            ),
            (
                "ir_embedded_calendar",
                "        if listing.event_calendars",
                "        if False",
                "test_embedded_issuer_calendar_is_collected_without_treating_calls_as_releases",
            ),
            (
                "ir_calendar_call",
                "                future_earnings |= event_day >= report_day",
                "                future_earnings |= False",
                "test_embedded_issuer_calendar_is_collected_without_treating_calls_as_releases",
            ),
            (
                "ir_calendar_partial",
                '            if section != "all" or ',
                "            if ",
                "test_embedded_issuer_calendar_is_collected_without_treating_calls_as_releases",
            ),
            (
                "ir_article_name",
                '        headline = article.get("headline") or article["nam',
                '        headline = article["headlin',
                "test_ir_article_name_and_local_publication_time_preserve_confirmed_release",
            ),
            (
                "ir_local_publication",
                "                published_day = datetime.fromisoformat(raw_published).date(",
                "                published_day = date.fromisoformat(raw_published",
                "test_ir_article_name_and_local_publication_time_preserve_confirmed_release",
            ),
            (
                "ir_publish_announcement",
                "(?:release|report|announce|publish)",
                "(?:release|report|announce)",
                "test_ir_article_name_and_local_publication_time_preserve_confirmed_release",
            ),
            (
                "ir_published_announcement",
                "(?:released|reported|announced|published)",
                "(?:released|reported|announced)",
                "test_ir_article_name_and_local_publication_time_preserve_confirmed_release",
            ),
            (
                "ir_split_offset",
                "                    page_number *= page_size",
                "                    pass",
                "test_oversized_ir_page_resumes_at_same_offset_with_full_bodies",
            ),
            (
                "ir_split_http_failure",
                '                    if str(error) != "response_too_large" or ',
                "                    if ",
                "test_ir_page_split_does_not_hide_single_item_or_http_failures",
            ),
            (
                "ir_head_pagination",
                '        if tag == "link" and "next" in attributes.get("rel", "").split()',
                "        if False",
                "test_head_next_link_cannot_hide_a_later_earnings_postponement",
            ),
            (
                "ir_listing_as_article",
                "    links.difference_update(visited)",
                "    pass",
                "test_ir_navigation_root_and_next_page_are_not_articles",
            ),
            (
                "ir_root_as_article",
                '                and target != source["article_prefix"]\n                and ',
                "                and ",
                "test_ir_navigation_root_and_next_page_are_not_articles",
            ),
            (
                "verified_exclusion",
                "        if excluded",
                "        if excluded and not held",
                "test_verified_exclusion_skips_earnings_and_turnover_and_replays",
            ),
            (
                "earnings_source_skip",
                '        inputs["skipped"]["earnings"] = "source_not_configured"',
                "        pass",
                "test_unknown_earnings_after_price_validation_skips_turnover",
            ),
            (
                "unverified_price_exclusion",
                '                    raise DataError("daily_price_reference_mismatch")',
                "                    pass",
                "test_unverified_prices_or_identity_cannot_prove_small_cap_exclusion",
            ),
        ]
    ]
    cases += [
        ("single_run.py", "test_universe_run.UniverseRunTests", control)
        for control in [
            (
                "exchange_identity",
                '        if data["output1"]["rsym"] != "D" + exchange + symbol',
                "        if False",
                "test_exchange_or_symbol_mismatch_is_held",
            ),
            (
                "collection_after_open",
                '            inputs["issues"].append("collection_outside_premarket")',
                "            pass",
                "test_collection_crossing_open_holds_only_late_symbols",
            ),
            (
                "universe_null_inputs",
                '        if execution == "single" or value is not Non',
                "        if Tru",
                "test_initial_failures_preserve_per_stock_price_collection_and_replay",
            ),
            (
                "universe_rejected_price",
                '            raise DataError(\n                "provider_rejected_request"\n                if execution == "single"\n                else "price_identity_mismatch"\n            ',
                '            raise DataError("provider_rejected_request"',
                "test_initial_failures_preserve_per_stock_price_collection_and_replay",
            ),
            (
                "earnings_open_crossing",
                '            inputs["issues"].append("collection_outside_premarket")',
                "            pass",
                "test_open_crossing_during_earnings_preserves_turnover_evidence_and_replays",
            ),
            (
                "ir_feed_terminal",
                "                if not rows",
                "                if len(rows) < 5",
                "test_dynamic_ir_walks_short_pages_until_explicit_empty_page",
            ),
            (
                "ir_feed_repeat",
                '                        raise DataError("earnings_feed_did_not_progress")',
                "                        pass",
                "test_dynamic_ir_repeated_page_is_a_failed_collection",
            ),
            (
                "ir_conflicting_announcements",
                '    if len({item["date"] for item in dates}) > 1',
                "    if False",
                "test_conflicting_future_ir_announcements_do_not_choose_an_arbitrary_date",
            ),
            (
                "ir_uncertainty_body",
                '            return {\n                "status": "unconfirmed",\n                "source": url,\n                "reason": "uncertain_earnings_announcement",\n            }',
                "            pass",
                "test_ir_body_qualifications_changes_and_call_dates_cannot_confirm_an_event",
            ),
            (
                "ir_call_date",
                '                event_dates.extend(\n                    re.findall(r"\\bon\\s+" + date_pattern, release_clause)\n                ',
                '                event_dates.extend(re.findall(r"\\bon\\s+" + date_pattern, sentence)',
                "test_ir_body_qualifications_changes_and_call_dates_cannot_confirm_an_event",
            ),
            (
                "ir_publication_time",
                "            if published_day >= as_of.astimezone(NY).date()",
                "            if False",
                "test_uncertain_ir_evidence_never_selects_a_candidate",
            ),
        ]
    ]
    cases += [
        ("single_run.py", "test_single_run.SingleRunTests", control)
        for control in [
            (
                "single_null_inputs",
                '        if execution == "single" or ',
                "        if ",
                "test_initial_failures_preserve_price_requests_and_replay",
            ),
            (
                "price_exclusion_collection",
                '    if result["status"] == "excluded":\n        inputs["skipped"] ',
                '    if False:\n        inputs["skipped"] ',
                "test_verified_price_failure_skips_remaining_sources",
            ),
            (
                "earnings_exclusion_collection",
                '    if result["status"] == "excluded":\n        inputs["skipped"][',
                '    if False:\n        inputs["skipped"][',
                "test_confirmed_near_earnings_skip_turnover",
            ),
        ]
    ]
    cases += [
        ("single_run.py", "test_execution_record.ExecutionRecordTests", control)
        for control in [
            (
                "single_response_time",
                "    execution = ExecutionRecord.start(\n        output, metadata, fetch, lambda: now or datetime.now(UTC)\n    ",
                "    execution = ExecutionRecord.start(output, metadata, fetch, lambda: now or as_of",
                "test_single_evaluation_keeps_start_time_when_responses_cross_open",
            ),
            (
                "single_replay_clock",
                'timestamp(record["as_of"])',
                "datetime.now(UTC)",
                "test_single_evaluation_keeps_start_time_when_responses_cross_open",
            ),
        ]
    ]
    cases.append(
        (
            "single_run.py",
            "test_universe_run.UniverseRunTests",
            (
                "universe_list_rate",
                "            time.sleep(1.0",
                "            time.sleep(0.3",
                "test_stock_all_requests_obey_separate_one_request_per_second_limit",
            ),
        )
    )
    cases.append(
        (
            "universe_run.py",
            "test_universe_run.UniverseRunTests",
            (
                "repligen_default_source",
                '            (\n                "RGEN",\n                "Repligen",\n                "https://investors.repligen.com/press-releases/default.aspx",\n                "https://investors.repligen.com/press-releases/news-details/",\n            ),\n',
                "",
                "test_repligen_archive_ignores_only_wholly_past_date_conflicts",
            ),
        )
    )
    cases += [
        (
            "execution_record.py",
            test.rsplit(".", 1)[0],
            (name, old, new, test.rsplit(".", 1)[1]),
        )
        for name, old, new, test in RECORD_CONTROLS
    ]
    cases += [
        ("single_run.py", "test_single_run.SingleRunTests", control)
        for control in [
            (
                "ir_failure_reason",
                "        reason = str(error)",
                '        reason = "source_fetch_or_parse_failed"',
                "test_earnings_fetch_failure_returns_complete_result",
            ),
            (
                "ir_invalid_response_details",
                '        reason = "invalid_response"',
                '        reason = "private upstream detail"',
                "test_earnings_invalid_responses_hide_upstream_details",
            ),
            (
                "ir_replay_error_propagation",
                '        if reason in ("replay_response_missing", "replay_request_mismatch")',
                "        if False",
                "test_earnings_replay_and_execution_errors_propagate",
            ),
        ]
    ]
    cases.append(
        (
            "single_run.py",
            "test_universe_run.UniverseRunTests",
            (
                "ir_failed_issue",
                '            inputs["issues"].append("earnings:" + inputs["earnings"]["reason"])',
                "            pass",
                "test_ir_fetch_failure_is_distinct_from_completed_search_without_evidence",
            ),
        )
    )
    for filename, test_class, (name, old, new, test) in cases:
        source = (ROOT / filename).read_text()
        if source.count(old) != 1:
            raise AssertionError(f"{name}: mutation target must occur exactly once")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "docs").mkdir()
            for relative in [
                "docs/single-run-contract.md",
                "docs/universe-run-contract.md",
                "single_run.py",
                "universe_run.py",
                "execution_record.py",
                "probe_earnings_sources.py",
                "probe_alpaca_trades.py",
                "test_single_run.py",
                "test_universe_run.py",
                "test_execution_record.py",
                "test_probe_alpaca_trades.py",
            ]:
                shutil.copyfile(ROOT / relative, folder / relative)
            command = [sys.executable, "-m", "unittest", test_class + "." + test]
            observations = []
            for content in [source, source.replace(old, new)]:
                (folder / filename).write_text(content)
                # Disable bytecode to guarantee the same fresh-import procedure for both runs.
                completed = subprocess.run(
                    [command[0], "-B", *command[1:]],
                    cwd=folder,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                observations.append(completed)
            good, broken = observations
            detected = (
                good.returncode == 0
                and broken.returncode != 0
                and "FAIL:" in broken.stderr
            )
            results.append(
                {
                    "control": name,
                    "correct_exit": good.returncode,
                    "broken_exit": broken.returncode,
                    "assertion_detected": detected,
                }
            )
            if not detected:
                print(broken.stderr)
    print(json.dumps({"python": sys.version.split()[0], "controls": results}, indent=2))
    return 0 if all(row["assertion_detected"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
