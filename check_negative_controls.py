"""Run the same behavior checks against isolated, deliberately broken copies."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONTROLS = [
    ('binary32_representation', "return struct.unpack('!f', struct.pack('!f', float(original)))[0] == float(reference)", 'return False',
     'test_binary32_reference_preserves_cent_boundary_prices_without_tolerance'),
    ('binary32_not_generic_tolerance', "return struct.unpack('!f', struct.pack('!f', float(original)))[0] == float(reference)", 'return True',
     'test_binary32_reference_preserves_cent_boundary_prices_without_tolerance'),
    ('binary32_precision_limit', "if abs(original - reference) >= Decimal('.005'):", 'if False:',
     'test_binary32_reference_preserves_cent_boundary_prices_without_tolerance'),
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
    ('non_common_detail_identity', "or row.get('isinCode') != evidence['isin']", '',
     'test_non_common_review_cannot_hide_missing_identity_evidence_or_other_listings'),
    ('non_common_listing_identity', "entry.get('symbol') != symbol or entry.get('isinCode') != evidence['isin']", 'False',
     'test_non_common_review_cannot_hide_missing_identity_evidence_or_other_listings'),
    ('non_common_pdf_digest', "if hashlib.sha256(body.encode()).hexdigest() != evidence['required_body_sha256']:", 'if False:',
     'test_reviewed_pdf_requires_exact_bytes_and_replays_without_network'),
    ('non_common_evidence', "if not all(fragment in text for fragment in evidence['required_text']):", 'if False:',
     'test_non_common_review_cannot_hide_missing_identity_evidence_or_other_listings'),
    ('non_common_review_date', "if date.fromisoformat(evidence['reviewed_on']) > as_of.astimezone(s.NY).date():", 'if False:',
     'test_non_common_review_cannot_hide_missing_identity_evidence_or_other_listings'),
    ('non_common_coverage', "listing['conflicts'] and set(listing['conflicts']) <= resolved", "listing['conflicts'] and resolved",
     'test_non_common_review_cannot_hide_missing_identity_evidence_or_other_listings'),
    ('non_common_exclusion', "if classification:", 'if False:',
     'test_reviewed_non_common_security_resolves_only_its_listing_conflict'),
    ('non_common_is_not_price_evaluation', 'if evaluated_exclusion else', "if counts['excluded'] else",
     'test_reviewed_non_common_security_resolves_only_its_listing_conflict'),
    ('listing_conflict_candidate', "elif symbol in universe['markets'][item['market']]['conflicts']:", 'elif False:',
     'test_listing_conflicts_are_preserved_per_symbol_for_reconciliation'),
    ('malformed_listing', "or not isinstance(row['securityType'], str)", '', 'test_malformed_listing_preserves_verified_partition_and_record'),
    ('list_omission', "not lists[''] or filtered != partitioned", 'False', 'test_missing_list_entries_never_claim_complete_coverage'),
    ('partial_results', "candidates[:3]", "[] if counts['held'] else candidates[:3]", 'test_partial_hold_keeps_verified_candidate_and_replays'),
    ('top_three_limit', 'candidates[:3]', 'candidates[:4]', 'test_top_three_use_automatically_collected_company_announcements'),
    ('volume_ranking', "-Decimal(stocks[symbol]['result']['metrics']['volume_ratio'])", "Decimal(stocks[symbol]['result']['metrics']['volume_ratio'])", 'test_top_three_use_automatically_collected_company_announcements'),
    ('unverified_tie', "] > 1]", "] > 100]", 'test_equal_volume_ratios_do_not_rank_by_turnover_lower_bounds'),
    ('no_candidates_vs_held', "else 'excluded' if evaluated_exclusion else 'held'", "else 'held'", 'test_verified_no_candidates_and_all_held_are_distinct'),
    ('exchange_identity', "data['output1']['rsym'] != 'D' + exchange + symbol", 'False', 'test_exchange_or_symbol_mismatch_is_held'),
    ('collection_after_open', "stock_input['issues'].append('collection_outside_premarket')", 'pass', 'test_collection_crossing_open_holds_only_late_symbols'),
    ('replay_report', "raise s.DataError('replay_report_mismatch')", 'pass', 'test_replay_rejects_modified_input_and_report_and_never_fetches'),
    ('replay_record', "raise s.DataError('record_integrity_mismatch')", 'pass', 'test_replay_rejects_modified_input_and_report_and_never_fetches'),
]


def main() -> int:
    results = []
    cases = [('single_run.py', 'test_single_run.SingleRunTests', control) for control in CONTROLS]
    cases += [('universe_run.py', 'test_universe_run.UniverseRunTests', control) for control in UNIVERSE_CONTROLS]
    cases += [('probe_earnings_sources.py', 'test_universe_run.UniverseRunTests', control) for control in [
        ('ir_probe_live_error', "if args.production and entry['status'] != 200:", 'if False:',
         'test_production_ir_probe_preserves_page_split_errors_and_replays'),
        ('ir_probe_replay_error', "if record.get('production') and entry['status'] != 200:", 'if False:',
         'test_production_ir_probe_preserves_page_split_errors_and_replays'),
    ]]
    cases += [('single_run.py', 'test_universe_run.UniverseRunTests', control) for control in [
        ('pdf_transport', "if body.startswith(b'%PDF-'):", 'if False:',
         'test_reviewed_pdf_requires_exact_bytes_and_replays_without_network'),
        ('ir_embedded_calendar', '        if listing.event_calendars:', '        if False:',
         'test_embedded_issuer_calendar_is_collected_without_treating_calls_as_releases'),
        ('ir_calendar_call', 'future_earnings |= event_day >= report_day', 'future_earnings |= False',
         'test_embedded_issuer_calendar_is_collected_without_treating_calls_as_releases'),
        ('ir_calendar_partial', "section != 'all' or not isinstance(events, list)", 'not isinstance(events, list)',
         'test_embedded_issuer_calendar_is_collected_without_treating_calls_as_releases'),
        ('ir_article_name', "headline = article.get('headline') or article['name']", "headline = article['headline']",
         'test_ir_article_name_and_local_publication_time_preserve_confirmed_release'),
        ('ir_local_publication', 'published_day = datetime.fromisoformat(raw_published).date()', 'published_day = date.fromisoformat(raw_published)',
         'test_ir_article_name_and_local_publication_time_preserve_confirmed_release'),
        ('ir_publish_announcement', '(?:release|report|announce|publish)', '(?:release|report|announce)',
         'test_ir_article_name_and_local_publication_time_preserve_confirmed_release'),
        ('ir_published_announcement', '(?:released|reported|announced|published)', '(?:released|reported|announced)',
         'test_ir_article_name_and_local_publication_time_preserve_confirmed_release'),
        ('ir_split_offset', '                    page_number *= page_size', '                    pass',
         'test_oversized_ir_page_resumes_at_same_offset_with_full_bodies'),
        ('ir_split_http_failure', "if str(error) != 'response_too_large' or page_size == 1:", 'if page_size == 1:',
         'test_ir_page_split_does_not_hide_single_item_or_http_failures'),
        ('ir_head_pagination', "if tag == 'link' and 'next' in attributes.get('rel', '').split():", 'if False:',
         'test_head_next_link_cannot_hide_a_later_earnings_postponement'),
        ('ir_listing_as_article', '    links.difference_update(visited)', '    pass',
         'test_ir_navigation_root_and_next_page_are_not_articles'),
        ('ir_root_as_article', " and target != source['article_prefix']", '',
         'test_ir_navigation_root_and_next_page_are_not_articles'),
        ('verified_exclusion', "        if excluded:\n", "        if excluded and not held:\n",
         'test_verified_exclusion_skips_earnings_and_turnover_and_replays'),
        ('earnings_source_skip', "        inputs['skipped']['earnings'] = 'source_not_configured'", '        pass',
         'test_unknown_earnings_after_price_validation_skips_turnover'),
        ('unverified_price_exclusion', "raise DataError('daily_price_reference_mismatch')", 'pass',
         'test_unverified_prices_or_identity_cannot_prove_small_cap_exclusion'),
    ]]
    cases += [('single_run.py', 'test_universe_run.UniverseRunTests', control) for control in [
        ('ir_feed_terminal', '                if not rows:\n                    break', '                if len(rows) < 5:\n                    break',
         'test_dynamic_ir_walks_short_pages_until_explicit_empty_page'),
        ('ir_feed_repeat', "raise DataError('earnings_feed_did_not_progress')", 'pass',
         'test_dynamic_ir_repeated_page_is_a_failed_collection'),
        ('ir_conflicting_announcements', "if len({item['date'] for item in dates}) > 1:", 'if False:',
         'test_conflicting_future_ir_announcements_do_not_choose_an_arbitrary_date'),
        ('ir_uncertainty_body', "return {'status': 'unconfirmed', 'source': url, 'reason': 'uncertain_earnings_announcement'}", 'pass',
         'test_ir_body_qualifications_changes_and_call_dates_cannot_confirm_an_event'),
        ('ir_call_date', 'date_pattern, release_clause))', 'date_pattern, sentence))',
         'test_ir_body_qualifications_changes_and_call_dates_cannot_confirm_an_event'),
        ('ir_publication_time', 'if published_day >= as_of.astimezone(NY).date():', 'if False:',
         'test_uncertain_ir_evidence_never_selects_a_candidate'),
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
                             'single_run.py', 'universe_run.py', 'probe_earnings_sources.py',
                             'test_single_run.py', 'test_universe_run.py']:
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
