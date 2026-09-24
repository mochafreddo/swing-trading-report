"""Exploratory SIP collection readiness; never certifies exact turnover."""

import argparse
import getpass
import hashlib
import json
import sys
import time
import warnings
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener
from zoneinfo import ZoneInfo

from single_run import NoRedirect


NY = ZoneInfo('America/New_York')
# Fixed experiment dates, not a general market calendar.
# NYSE 2025 calendar confirms the November 28 early close.
SESSIONS = {'2026-09-11': '16:00', '2025-11-28': '13:00'}
SYMBOLS = ['MU', 'AAPL', 'XOM']
ENDPOINT = 'https://data.alpaca.markets/v2/stocks/trades'
# Alpaca stock bar-condition table, 2026-09-24; these groups are diagnostics, not a turnover contract.
CONDITIONS_BY_TAPE = {'A': set(' BCEFHIKLMNOPQRTUVXZ45679'),
                      'B': set(' BCEFHIKLMNOPQRTUVXZ45679'),
                      'C': set('@ABCDFGHIKLMNOPQRTUVWXYZ45679')}


def window(day):
    start = datetime.fromisoformat(day + 'T09:30').replace(tzinfo=NY)
    close = datetime.fromisoformat(day + 'T' + SESSIONS[day]).replace(tzinfo=NY)
    return start, close


def request_parameters(day):
    start, close = window(day)
    return {'symbols': ','.join(SYMBOLS), 'start': start.isoformat(),
            'end': (close + timedelta(minutes=5)).isoformat(), 'feed': 'sip',
            'currency': 'USD', 'limit': 10000, 'sort': 'asc', 'asof': day}


def inspect_pages(pages, day, feed='sip'):
    if feed != 'sip':
        raise ValueError('single_exchange_feed_rejected')
    start, close = window(day)
    end = close + timedelta(minutes=5)
    tokens, ids, counts, conditions = set(), set(), Counter(), Counter()
    recurrences, affected = Counter(), set()
    updates = Counter()
    unknown_update = False
    session_conditions, closing_examples = Counter(), {}
    diagnostic_totals = {symbol: {} for symbol in SYMBOLS}
    amounts = {symbol: Decimal(0) for symbol in SYMBOLS}
    expected = None
    for index, page in enumerate(pages):
        if index and expected is None:
            raise ValueError('page_after_terminal_response')
        if page.get('requested_page_token') != expected:
            raise ValueError('page_chain_broken')
        data = json.loads(page['body'], parse_float=Decimal)
        if not isinstance(data.get('trades'), dict) or 'next_page_token' not in data:
            raise ValueError('unexpected_trade_envelope')
        for symbol, rows in data['trades'].items():
            if symbol not in SYMBOLS:
                raise ValueError('unexpected_symbol')
            for row in rows:
                stamp = datetime.fromisoformat(row['t'].replace('Z', '+00:00'))
                if stamp.tzinfo is None or not start <= stamp <= end:
                    raise ValueError('trade_outside_requested_window')
                price, size = Decimal(str(row['p'])), Decimal(str(row['s']))
                if not price.is_finite() or not size.is_finite() or price <= 0 or size <= 0:
                    raise ValueError('invalid_price_or_size')
                identity = (symbol, row['z'], row['x'], row['i'])
                if identity in ids:
                    recurrences[symbol + '/' + row['x']] += 1
                    affected.add(symbol)
                ids.add(identity)
                if 'u' in row:
                    update = row['u'] if row['u'] in ('canceled', 'incorrect', 'corrected') else 'unknown'
                    updates[symbol + '/' + update] += 1
                    affected.add(symbol)
                    unknown_update |= update == 'unknown'
                if not isinstance(row['c'], list) or not all(isinstance(c, str) for c in row['c']):
                    raise ValueError('invalid_trade_conditions')
                bucket = 'before_close' if stamp < close else 'at_or_after_close'
                if stamp >= close and '6' in row['c']:
                    session_conditions[symbol + '/closing_trade_at_or_after_close'] += 1
                    closing_examples.setdefault(symbol, {'t': row['t'], 'c': row['c']})
                if stamp < close and any(c in ('T', 'U') for c in row['c']):
                    session_conditions[symbol + '/extended_hours_before_close'] += 1
                counts[symbol + '/' + bucket] += 1
                conditions['/'.join([symbol, bucket, ','.join(sorted(row['c']))])] += 1
                known = CONDITIONS_BY_TAPE.get(row['z'], set())
                if row.get('u') in ('canceled', 'incorrect'):
                    group = 'canceled_or_incorrect'
                elif (not row['c'] or any(c not in known for c in row['c'])
                      or ('u' in row and row['u'] != 'corrected')):
                    group = 'unknown'
                elif any(c in ('M', 'Q', '9') for c in row['c']):
                    group = 'non_volume'
                elif any(c in ('T', 'U') for c in row['c']):
                    group = 'extended_hours'
                elif stamp < close:
                    group = 'before_close'
                elif '6' in row['c']:
                    group = 'closing_after_close'
                else:
                    group = 'other_after_close'
                total = diagnostic_totals[symbol].setdefault(group, {'rows': 0, 'volume': Decimal(0), 'amount_usd': Decimal(0)})
                total['rows'] += 1
                total['volume'] += size
                total['amount_usd'] += price * size
                # Diagnostic sum of returned rows, deliberately not session eligibility.
                amounts[symbol] += price * size
        expected = data.get('next_page_token')
        if expected is not None:
            if not isinstance(expected, str) or not expected or expected in tokens:
                raise ValueError('repeated_or_invalid_page_token')
            tokens.add(expected)
    complete = bool(pages) and expected is None
    observed = sorted({i[0] for i in ids})
    issues = []
    if recurrences:
        issues.append('duplicate_trade_identity_requires_review')
    if updates:
        issues.append('historical_trade_updates_require_review')
    if unknown_update:
        issues.append('unknown_trade_update_requires_review')
    if session_conditions:
        issues.append('session_conditions_require_review')
    return {'pagination_complete': complete, 'pages': len(pages), 'counts': dict(counts),
            'condition_counts': dict(conditions), 'observed_symbols': sorted({i[0] for i in ids}),
            'symbols_without_observed_trades': sorted(set(SYMBOLS) - set(observed)),
            'identity_recurrences': dict(recurrences),
            'trade_update_counts': dict(updates),
            'session_condition_counts': dict(session_conditions),
            'closing_trade_examples': closing_examples,
            'diagnostic_condition_totals': {symbol: {group: {'rows': total['rows'], 'volume': str(total['volume']),
                                                            'amount_usd': str(total['amount_usd'])}
                                                    for group, total in groups.items()}
                                             for symbol, groups in diagnostic_totals.items()},
            'validation_status': 'held',
            'validation_issues': issues,
            'returned_row_amount_usd': {k: str(v) if k in observed and k not in affected else None
                                        for k, v in amounts.items()},
            'exact_regular_turnover_verified': False,
            'unresolved': ['trade_eligibility', 'historical_corrections_and_cancels',
                           'late_reports', 'trade_identity_contract', 'independent_total_reconciliation']}


def self_check():
    from contextlib import redirect_stderr
    from io import StringIO
    from tempfile import TemporaryDirectory
    from unittest.mock import MagicMock, patch

    with TemporaryDirectory() as root:
        existing = Path(root) / 'existing'
        existing.mkdir()
        sentinel = existing / 'record.json'
        sentinel.write_bytes(b'preserve existing record')
        with patch.object(getpass, 'getpass', side_effect=AssertionError('unexpected credential prompt')):
            with patch.object(sys.stdin, 'isatty', return_value=True):
                try:
                    collect('2026-09-11', existing, 1)
                except FileExistsError:
                    pass
                else:
                    raise AssertionError('existing output accepted')
            with patch.object(sys.stdin, 'isatty', return_value=False):
                fresh = Path(root) / 'fresh'
                try:
                    collect('2026-09-11', fresh, 1)
                except ValueError:
                    pass
                else:
                    raise AssertionError('noninteractive input accepted')
                assert not fresh.exists()
        assert sentinel.read_bytes() == b'preserve existing record'

    row = {'t': '2026-09-11T20:00:00Z', 'p': 100, 's': 2, 'x': 'Q', 'z': 'C', 'i': 1, 'c': ['6']}
    page = {'requested_page_token': None,
            'body': json.dumps({'trades': {'MU': [row]}, 'next_page_token': None})}
    result = inspect_pages([page], '2026-09-11')
    assert result['counts']['MU/at_or_after_close'] == 1
    assert result['returned_row_amount_usd']['MU'] == '200'
    assert result['pagination_complete'] and not result['exact_regular_turnover_verified']
    incomplete = {'requested_page_token': None,
                  'body': json.dumps({'trades': {'MU': [row]}, 'next_page_token': 'more'})}
    try:
        assert inspect_pages([incomplete], '2026-09-11')['pagination_complete']
    except AssertionError:
        pass
    else:
        raise AssertionError('missing_page_accepted')
    failures = 0
    bad_duplicate = dict(page, body=json.dumps({'trades': {'MU': [row, row]}, 'next_page_token': None}))
    duplicate_result = inspect_pages([bad_duplicate], '2026-09-11')
    assert duplicate_result['identity_recurrences'] == {'MU/Q': 1}
    assert duplicate_result['returned_row_amount_usd']['MU'] is None
    assert duplicate_result['validation_status'] == 'held'
    bad_price = dict(page, body=json.dumps({'trades': {'MU': [dict(row, p=0)]}, 'next_page_token': None}))
    bad_bar = dict(page, body=json.dumps({'bars': {'MU': [{'v': 2, 'vw': 100}]}, 'next_page_token': None}))
    missing_token = dict(page, body=json.dumps({'trades': {'MU': [row]}}))
    for pages, feed in [([page], 'iex'), ([bad_price], 'sip'),
                        ([bad_bar], 'sip'), ([missing_token], 'sip'),
                        ([incomplete, dict(incomplete, requested_page_token='more')], 'sip')]:
        try:
            inspect_pages(pages, '2026-09-11', feed)
        except ValueError:
            failures += 1
    assert failures == 5
    early_row = dict(row, t='2025-11-28T18:00:00Z')
    early_page = dict(page, body=json.dumps({'trades': {'MU': [early_row]}, 'next_page_token': None}))
    assert inspect_pages([early_page], '2025-11-28')['counts']['MU/at_or_after_close'] == 1
    for outcome in ('interrupted_read', 'interrupted_sleep', 'timeout', 'complete'):
        with TemporaryDirectory() as root:
            output = Path(root) / 'run'
            response = MagicMock()
            response.__enter__.return_value = response
            body = json.dumps({'trades': {'MU': [row]},
                               'next_page_token': None if outcome == 'complete' else 'more'}).encode()
            response.read.side_effect = [TimeoutError()] if outcome == 'timeout' else [body, KeyboardInterrupt()]
            opener = MagicMock()
            opener.open.return_value = response
            progress = StringIO()
            checkpoints = []

            def open_response(*args, **kwargs):
                checkpoint = json.loads((output / 'record.json').read_text())
                assert checkpoint['error'] == 'collection_in_progress'
                assert len(checkpoint['pages']) == len(checkpoints)
                assert progress.getvalue()
                checkpoints.append(checkpoint)
                return response

            opener.open.side_effect = open_response
            with patch.object(sys.stdin, 'isatty', return_value=True), \
                    patch.object(getpass, 'getpass', side_effect=['synthetic-key', 'synthetic-secret']), \
                    patch(__name__ + '.build_opener', return_value=opener), \
                    patch.object(time, 'sleep', side_effect=KeyboardInterrupt() if outcome == 'interrupted_sleep' else None), \
                    redirect_stderr(progress):
                collected = collect('2026-09-11', output, 2)
            saved = json.loads((output / 'record.json').read_text())
            assert saved == collected
            assert len(saved['pages']) == (0 if outcome == 'timeout' else 1)
            expected_error = {'interrupted_read': 'interrupted', 'interrupted_sleep': 'interrupted',
                              'timeout': 'transport_or_response_invalid', 'complete': None}[outcome]
            assert saved['error'] == expected_error
            assert inspect_pages(saved['pages'], saved['day'])['pagination_complete'] == (outcome == 'complete')
            assert progress.getvalue()
            for value in ('synthetic-key', 'synthetic-secret'):
                assert value not in progress.getvalue() + (output / 'record.json').read_text()
    return {'mock_only': True, 'negative_controls_detected': 7,
            'closing_boundary_examples': 2, 'collection_preflight_cases': 2,
            'collection_recovery_cases': 4,
            'live_access_verified': False}


def load_record(path):
    raw = path.read_bytes()
    record = json.loads(raw)
    if record['day'] not in SESSIONS or record['feed'] != 'sip' or record['symbols'] != SYMBOLS:
        raise ValueError('saved_request_scope_mismatch')
    # Original probe records predate explicit request metadata; their fixed scope is validated above.
    if 'request' in record and record['request'] != request_parameters(record['day']):
        raise ValueError('saved_request_parameters_mismatch')
    for page in record['pages']:
        if hashlib.sha256(page['body'].encode()).hexdigest() != page['sha256']:
            raise ValueError('saved_body_hash_mismatch')
    inspect_pages(record['pages'], record['day'], record['feed'])
    return record, hashlib.sha256(raw).hexdigest()


def collect(day, output, max_pages, resume=None):
    pages, token, parent_hash, previous_elapsed = [], None, None, 0
    if resume is not None:
        previous, parent_hash = load_record(resume)
        day, pages = previous['day'], previous['pages']
        previous_elapsed = previous['elapsed_seconds']
        if pages:
            token = json.loads(pages[-1]['body'])['next_page_token']
            if token is None:
                raise ValueError('saved_pagination_already_complete; use --replay instead')
    start, close = window(day)
    if close + timedelta(minutes=20) > datetime.now(timezone.utc):
        raise ValueError('historical_window_not_ready')
    if output.exists():
        raise FileExistsError(f'Output already exists: {output}. Use a new --output directory; existing data will not be overwritten.')
    if not sys.stdin.isatty():
        raise ValueError('Interactive terminal required for hidden credential input. Run directly in a terminal without piping stdin.')
    # Interactive hidden input only. No credential file, environment, token issue or orders.
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        key = getpass.getpass('Alpaca API key: ')
        secret = getpass.getpass('Alpaca API secret: ')
    if not key or not secret:
        raise ValueError('credentials_missing')
    output.mkdir(parents=True, exist_ok=False)
    error = None
    began = time.monotonic()

    def save_record(state):
        record = {'day': day, 'feed': 'sip', 'symbols': SYMBOLS, 'pages': pages, 'error': state,
                  'elapsed_seconds': round(previous_elapsed + time.monotonic() - began, 3),
                  'request': request_parameters(day)}
        if parent_hash is not None:
            record['resumed_from_sha256'] = parent_hash
        # TODO: #233 - Replace full-record checkpoints with incremental storage before scaling beyond this three-symbol probe.
        temporary = output / 'record.json.tmp'
        temporary.write_text(json.dumps(record, ensure_ascii=False) + '\n')
        temporary.replace(output / 'record.json')
        return record

    save_record('collection_in_progress')
    try:
        for index in range(max_pages):
            query = request_parameters(day)
            if token is not None:
                query['page_token'] = token
            request = Request(ENDPOINT + '?' + urlencode(query), headers={
                'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret,
                'User-Agent': 'swing-trading-report-data-probe/0.1'})
            print(f'[{index + 1}/{max_pages}] requesting page; elapsed {time.monotonic() - began:.1f}s', file=sys.stderr, flush=True)
            try:
                with build_opener(NoRedirect).open(request, timeout=30) as response:
                    raw = response.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise ValueError('response_too_large')
                body = raw.decode('utf-8')
                if key in body or secret in body:
                    raise ValueError('credential_echo_rejected')
                data = json.loads(body)
                if not isinstance(data.get('trades'), dict) or 'next_page_token' not in data:
                    raise ValueError('unexpected_trade_envelope')
            except HTTPError as failure:
                error = 'http_' + str(failure.code)
                failure.close()
                break
            except (URLError, TimeoutError, OSError, UnicodeError, ValueError):
                error = 'transport_or_response_invalid'
                break
            pages.append({'requested_page_token': token, 'checked_at': datetime.now(timezone.utc).isoformat(),
                          'sha256': hashlib.sha256(raw).hexdigest(), 'body': body})
            save_record('collection_in_progress')
            row_count = sum(len(rows) for rows in data['trades'].values())
            print(f'[{index + 1}/{max_pages}] saved {row_count} rows; elapsed {time.monotonic() - began:.1f}s', file=sys.stderr, flush=True)
            next_token = data.get('next_page_token')
            if next_token is None:
                break
            if not isinstance(next_token, str) or not next_token or next_token == token:
                error = 'invalid_or_repeated_page_token'
                break
            token = next_token
            if index + 1 < max_pages:
                time.sleep(0.35)
    except KeyboardInterrupt:
        error = 'interrupted'
    finally:
        key = secret = ''
    record = save_record(error)
    status = error or ('complete' if pages and json.loads(pages[-1]['body'])['next_page_token'] is None
                       else 'page_limit_reached')
    print(f'Saved {len(pages)} pages to {output / "record.json"}; collection: {status}; validation: pending',
          file=sys.stderr, flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--self-check', action='store_true')
    actions.add_argument('--day', choices=SESSIONS, help='Live data-only GET; prompts for approved credentials')
    actions.add_argument('--replay', type=Path)
    actions.add_argument('--resume', type=Path, help='Continue a saved record into a new output directory')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--max-pages', type=int, default=100, help='Maximum additional pages for this invocation (1..100)')
    args = parser.parse_args()
    if args.self_check:
        print(json.dumps(self_check(), indent=2))
        return
    if (args.day or args.resume) and (args.output is None or not 1 <= args.max_pages <= 100):
        parser.error('--day/--resume requires --output and 1..100 --max-pages')
    try:
        record = (collect(args.day, args.output, args.max_pages, args.resume)
                  if args.day or args.resume else load_record(args.replay)[0])
        summary = inspect_pages(record['pages'], record['day'], record['feed'])
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    summary['collection_error'] = record['error']
    summary['elapsed_seconds'] = record['elapsed_seconds']
    summary['collection_status'] = ('in_progress' if record['error'] == 'collection_in_progress' else
                                    'interrupted' if record['error'] == 'interrupted' else
                                    'failed' if record['error'] else
                                    'complete' if summary['pagination_complete'] else 'page_limit_reached')
    if record['error']:
        summary['pagination_complete'] = False
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
