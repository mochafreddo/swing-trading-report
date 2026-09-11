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
    ('held_quote_validation', "if not all(key in inputs for key in ('stock', 'calendar', 'bars_0', 'bars_1')):", 'if held:', 'test_live_session_hold_does_not_hide_invalid_quotes'),
    ('breakout_equality', "last['clos'] > base", "last['clos'] >= base", 'test_breakout_equality_is_excluded'),
    ('volume_boundary', ">= avg_volume * Decimal(RULES['volume_multiple'])", ">= avg_volume * Decimal('1.4')", 'test_volume_multiple_below_boundary_is_excluded'),
    ('market_cap_boundary', ">= Decimal(RULES['market_cap_min_usd'])", ">= Decimal('9000000000')", 'test_market_cap_below_boundary_is_excluded'),
    ('liquidity_boundary', ">= Decimal(RULES['turnover_min_usd'])", "> Decimal(RULES['turnover_min_usd'])", 'test_turnover_inclusive_boundary'),
    ('sma_equality', "last['clos'] > sma", "last['clos'] >= sma", 'test_sma_equality_is_excluded'),
    ('bad_quotes', "raise DataError('invalid_ohlc')", 'pass', 'test_bad_quotes_are_held_without_a_price_plan'),
    ('estimated_earnings', "return {'status': 'unconfirmed', 'source': url, 'reason': 'uncertain_earnings_announcement'}", 'pass', 'test_unconfirmed_and_estimated_earnings_are_held'),
    ('newer_earnings_change', "return max(newer_changes, key=lambda item: timestamp(item['published_at'])) if newer_changes else next_event", 'return next_event', 'test_newer_earnings_postponement_invalidates_original_announcement'),
    ('missing_earnings', "if inputs['earnings'].get('status') != 'confirmed':", 'if False:', 'test_unconfirmed_and_estimated_earnings_are_held'),
    ('earnings_fifth_session', "event > date.fromisoformat(inputs['calendar']['future'][-1])", "event >= date.fromisoformat(inputs['calendar']['future'][-1])", 'test_earnings_window_includes_today_fifth_session_and_weekend'),
    ('wrong_target', "'target': entry + risk * 2", "'target': entry + risk * 3", 'test_selected_report_and_offline_replay'),
    ('unverified_live_data', "inputs['issues'].append('kis_regular_session_unverified')", 'pass', 'test_unverified_live_session_cannot_become_candidate'),
]


def main() -> int:
    source = (ROOT / 'single_run.py').read_text()
    results = []
    for name, old, new, test in CONTROLS:
        if source.count(old) != 1:
            raise AssertionError(f'{name}: mutation target must occur exactly once')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'docs').mkdir()
            shutil.copyfile(ROOT / 'docs/single-run-contract.md', folder / 'docs/single-run-contract.md')
            shutil.copyfile(ROOT / 'test_single_run.py', folder / 'test_single_run.py')
            command = [sys.executable, '-m', 'unittest', 'test_single_run.SingleRunTests.' + test]
            observations = []
            for content in [source, source.replace(old, new)]:
                (folder / 'single_run.py').write_text(content)
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
