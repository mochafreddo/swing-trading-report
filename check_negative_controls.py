"""Run the same behavior checks against isolated, deliberately broken copies."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONTROLS = [
    ('calendar_rate_limit', 'time.sleep(0.35)', 'time.sleep(0.15)', 'test_calendar_collection_respects_three_requests_per_second'),
    ('held_quote_validation', "if not all(key in inputs for key in ('stock', 'calendar', 'bars_0')):", 'if held:', 'test_live_session_hold_does_not_hide_invalid_quotes'),
    ('breakout_equality', "last['clos'] > base", "last['clos'] >= base", 'test_breakout_equality_is_excluded'),
    ('volume_boundary', ">= avg_volume * Decimal(RULES['volume_multiple'])", ">= avg_volume * Decimal('1.4')", 'test_volume_multiple_below_boundary_is_excluded'),
    ('market_cap_boundary', ">= Decimal(RULES['market_cap_min_usd'])", ">= Decimal('9000000000')", 'test_market_cap_below_boundary_is_excluded'),
    ('liquidity_boundary', "turnover < Decimal(RULES['turnover_min_usd'])", "turnover <= Decimal(RULES['turnover_min_usd'])", 'test_turnover_inclusive_boundary'),
    ('sma_equality', "last['clos'] > sma", "last['clos'] >= sma", 'test_sma_equality_is_excluded'),
    ('bad_quotes', "raise DataError('invalid_ohlc')", 'pass', 'test_bad_quotes_are_held_without_a_price_plan'),
    ('estimated_earnings', "return {'status': 'unconfirmed', 'source': url, 'reason': 'uncertain_earnings_announcement'}", 'pass', 'test_unconfirmed_and_estimated_earnings_are_held'),
    ('newer_earnings_change', "return max(newer_changes, key=lambda item: timestamp(item['published_at'])) if newer_changes else next_event", 'return next_event', 'test_newer_earnings_postponement_invalidates_original_announcement'),
    ('missing_earnings', "if inputs['earnings'].get('status') != 'confirmed':", 'if False:', 'test_unconfirmed_and_estimated_earnings_are_held'),
    ('earnings_fifth_session', "event > date.fromisoformat(inputs['calendar']['future'][-1])", "event >= date.fromisoformat(inputs['calendar']['future'][-1])", 'test_earnings_window_includes_today_fifth_session_and_weekend'),
    ('wrong_target', "'target': entry + risk * 2", "'target': entry + risk * 3", 'test_selected_report_and_offline_replay'),
    ('unverified_live_data', 'if any(meta.get(key) != value for key, value in required.items()):', 'if False:', 'test_unverified_live_session_cannot_become_candidate'),
    ('reference_price', "raise DataError('daily_price_reference_mismatch')", 'pass', 'test_reference_disagreement_or_unknown_adjustment_is_held'),
    ('reference_volume', "raise DataError('invalid_daily_volume_units')", 'pass', 'test_reference_disagreement_or_unknown_adjustment_is_held'),
    ('corporate_action_metadata', "raise DataError('corporate_action_metadata_invalid')", 'pass', 'test_reference_disagreement_or_unknown_adjustment_is_held'),
    ('split_window', "if reference['events'].get('splits'):", 'if False:', 'test_split_window_is_held'),
    ('report_day_split', 'datetime.combine(report_day + timedelta(days=1), datetime.min.time(), NY)', 'datetime.combine(report_day, datetime.min.time(), NY)', 'test_report_day_split_is_checked_before_publishing_prices'),
    ('dividend_policy', "if reference['events'].get('splits'):", "if reference['events'].get('splits') or reference['events'].get('dividends'):", 'test_cash_dividend_keeps_the_unadjusted_price_plan'),
    ('amount_rounding', 'max(Decimal(0), amount - 1)', 'amount', 'test_turnover_inclusive_boundary'),
    ('insufficient_bound', "raise DataError('turnover_lower_bound_insufficient')", "return result | {'status': 'excluded'}", 'test_turnover_inclusive_boundary'),
    ('missing_minutes', 'if set(found) != set(expected):', 'if False:', 'test_invalid_regular_turnover_is_held'),
    ('duplicate_minutes', "raise DataError('duplicate_or_unordered_minutes')", 'pass', 'test_invalid_regular_turnover_is_held'),
    ('minute_amount_units', "raise DataError('turnover_unit_or_session_mismatch')", 'pass', 'test_invalid_regular_turnover_is_held'),
    ('minute_timezone', "raise DataError('minute_timezone_mismatch')", 'pass', 'test_invalid_regular_turnover_is_held'),
]

UNIVERSE_CONTROLS = [
    ('malformed_listing', "or not isinstance(row['securityType'], str)", '', 'test_malformed_listing_preserves_verified_partition_and_record'),
    ('list_omission', "not lists[''] or filtered != partitioned", 'False', 'test_missing_list_entries_never_claim_complete_coverage'),
    ('partial_results', "candidates[:3]", "[] if counts['held'] else candidates[:3]", 'test_partial_hold_keeps_verified_candidate_and_replays'),
    ('top_three_limit', 'candidates[:3]', 'candidates[:4]', 'test_top_three_use_automatically_collected_company_announcements'),
    ('volume_ranking', "-Decimal(stocks[symbol]['result']['metrics']['volume_ratio'])", "Decimal(stocks[symbol]['result']['metrics']['volume_ratio'])", 'test_top_three_use_automatically_collected_company_announcements'),
    ('unverified_tie', "] > 1]", "] > 100]", 'test_equal_volume_ratios_do_not_rank_by_turnover_lower_bounds'),
    ('no_candidates_vs_held', "else 'excluded' if counts['excluded'] else 'held'", "else 'held'", 'test_verified_no_candidates_and_all_held_are_distinct'),
    ('exchange_identity', "data['output1']['rsym'] != 'D' + exchange + symbol", 'False', 'test_exchange_or_symbol_mismatch_is_held'),
    ('collection_after_open', "stock_input['issues'].append('collection_outside_premarket')", 'pass', 'test_collection_crossing_open_holds_only_late_symbols'),
    ('replay_report', "raise s.DataError('replay_report_mismatch')", 'pass', 'test_replay_rejects_modified_input_and_report_and_never_fetches'),
    ('replay_record', "raise s.DataError('record_integrity_mismatch')", 'pass', 'test_replay_rejects_modified_input_and_report_and_never_fetches'),
]


def main() -> int:
    results = []
    cases = [('single_run.py', 'test_single_run.SingleRunTests', control) for control in CONTROLS]
    cases += [('universe_run.py', 'test_universe_run.UniverseRunTests', control) for control in UNIVERSE_CONTROLS]
    cases += [('single_run.py', 'test_universe_run.UniverseRunTests', control) for control in [
        ('verified_exclusion', "        if excluded:\n", "        if excluded and not held:\n",
         'test_verified_exclusion_skips_earnings_and_turnover_and_replays'),
        ('earnings_source_skip', "        inputs['skipped']['earnings'] = 'source_not_configured'", '        pass',
         'test_unknown_earnings_after_price_validation_skips_turnover'),
        ('unverified_price_exclusion', "raise DataError('daily_price_reference_mismatch')", 'pass',
         'test_unverified_prices_or_identity_cannot_prove_small_cap_exclusion'),
    ]]
    cases += [('single_run.py', 'test_single_run.SingleRunTests', control) for control in [
        ('price_exclusion_collection', "    if result['status'] == 'excluded':\n        inputs['skipped'] =", "    if False:\n        inputs['skipped'] =",
         'test_verified_price_failure_skips_remaining_sources'),
        ('earnings_exclusion_collection', "    if result['status'] == 'excluded':\n        inputs['skipped']['turnover']",
         "    if False:\n        inputs['skipped']['turnover']", 'test_confirmed_near_earnings_skip_turnover'),
    ]]
    cases.append(('single_run.py', 'test_universe_run.UniverseRunTests',
                  ('universe_list_rate', 'time.sleep(1.05)', 'time.sleep(0.35)',
                   'test_stock_all_requests_obey_separate_one_request_per_second_limit')))
    for filename, test_class, (name, old, new, test) in cases:
        source = (ROOT / filename).read_text()
        if source.count(old) != 1:
            raise AssertionError(f'{name}: mutation target must occur exactly once')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'docs').mkdir()
            for relative in ['docs/single-run-contract.md', 'docs/universe-run-contract.md',
                             'single_run.py', 'universe_run.py', 'test_single_run.py', 'test_universe_run.py']:
                shutil.copyfile(ROOT / relative, folder / relative)
            command = [sys.executable, '-m', 'unittest', test_class + '.' + test]
            observations = []
            for content in [source, source.replace(old, new)]:
                (folder / filename).write_text(content)
                # Disable bytecode to guarantee the same fresh-import procedure for both runs.
                completed = subprocess.run([command[0], '-B', *command[1:]], cwd=folder,
                                           capture_output=True, text=True, timeout=30)
                observations.append(completed)
            good, broken = observations
            detected = good.returncode == 0 and broken.returncode != 0 and 'FAIL:' in broken.stderr
            results.append({'control': name, 'correct_exit': good.returncode,
                            'broken_exit': broken.returncode, 'assertion_detected': detected})
            if not detected:
                print(broken.stderr)
    print(json.dumps({'python': sys.version.split()[0], 'controls': results}, indent=2))
    return 0 if all(row['assertion_detected'] for row in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
