"""Exercise public-response collection through saved reports and offline replay."""

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import universe_run as u
from test_single_run import DAY, NOW, NEWS_URL, PublicResponses


class UniverseResponses:
    def __init__(self):
        self.sources = {'MU': PublicResponses(), 'IBM': PublicResponses()}
        self.sources['IBM'].stock.update(symbol='IBM', market='NYSE')
        self.earnings_sources = {}

    def add_company(self, symbol, ratio):
        source = PublicResponses()
        source.stock.update(symbol=symbol, market='NASDAQ')
        source.bars[-1]['tvol'] = str(ratio * 1_000_000)
        self.sources[symbol] = source
        self.earnings_sources[symbol] = {'company': symbol + ' Corporation',
                                       'listing_url': 'https://ir.example.com/' + symbol,
                                       'article_prefix': 'https://ir.example.com/releases/' + symbol + '/'}

    def __call__(self, url):
        query = parse_qs(urlparse(url).query)
        path = urlparse(url).path
        if urlparse(url).netloc == 'ir.example.com':
            symbol = path.rstrip('/').rsplit('/', 1)[-1] if not path.endswith('/release') else path.split('/')[-2]
            config = self.earnings_sources[symbol]
            if url == config['listing_url']:
                return '<a href="' + config['article_prefix'] + 'release">Earnings</a>'
            return self.sources[symbol](NEWS_URL).replace('Micron Technology', config['company'])
        if path.endswith('/stocks/all'):
            rows = [s.stock for s in self.sources.values()
                    if s.stock['market'] == query['market'][0]
                    and s.stock['securityType'] == query.get('securityType', ['STOCK'])[0]]
            return json.dumps({'result': sorted(rows, key=lambda r: r['symbol'])})
        if path.endswith('/stocks'):
            return json.dumps({'result': [self.sources[s].stock for s in query['symbols'][0].split(',')]})
        symbol = query.get('SYMB', [path.rsplit('/', 1)[-1]])[0]
        if symbol in self.sources:
            source = self.sources[symbol]
            body = source(url.replace('/chart/' + symbol, '/chart/MU'))
            if symbol != 'MU':
                exchange = 'DNYS' if source.stock['market'] == 'NYSE' else 'DNAS'
                body = body.replace('DNASMU', exchange + symbol).replace('"symbol": "MU"', '"symbol": "' + symbol + '"')
                if source.stock['market'] == 'NYSE':
                    body = body.replace('"NMS"', '"NYQ"')
            return body
        return self.sources['MU'](url)


class UniverseRunTests(unittest.TestCase):
    def run_case(self, source=None, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            record = u.run(out, DAY, fetch=source or UniverseResponses(), now=NOW,
                           synthetic=True, **kwargs)
            saved = json.loads((out / 'record.json').read_text())
            self.assertEqual(saved, record)
            self.assertEqual(u.replay(out), record)
            return record, (out / 'report.md').read_text()

    def test_partial_hold_keeps_verified_candidate_and_replays(self):
        record, report = self.run_case()
        self.assertTrue(record['result']['coverage_complete'])
        self.assertEqual(record['result']['candidates'], ['MU'])
        self.assertEqual(record['result']['counts'], {'total': 2, 'selected': 1, 'excluded': 0, 'held': 1})
        self.assertIsNotNone(record['inputs']['stocks']['MU']['result']['plan'])
        self.assertIn('earnings_source_not_configured', record['inputs']['stocks']['IBM']['result']['reasons'])
        self.assertIn('보류 1', report)

    def test_top_three_use_automatically_collected_company_announcements(self):
        source = UniverseResponses()
        for symbol, ratio in [('AAA', 2), ('BBB', 4), ('CCC', 3), ('DDD', 5)]:
            source.add_company(symbol, ratio)
        record, report = self.run_case(source, earnings_sources=source.earnings_sources)
        self.assertEqual(record['result']['candidates'], ['DDD', 'BBB', 'CCC'])
        self.assertEqual(record['result']['counts']['selected'], 5)
        self.assertIn('## 3. CCC', report)
        self.assertNotIn('## 4.', report)

    def test_equal_volume_ratios_do_not_rank_by_turnover_lower_bounds(self):
        source = UniverseResponses()
        source.add_company('AAA', 2)
        source.add_company('BBB', 2)
        source.add_company('CCC', 3)
        record, report = self.run_case(source, earnings_sources=source.earnings_sources)
        self.assertEqual(record['result']['candidates'], ['CCC', 'MU'])
        self.assertFalse(record['result']['ranking_complete'])
        for symbol in ('AAA', 'BBB'):
            self.assertEqual(record['inputs']['stocks'][symbol]['result']['status'], 'held')
            self.assertIsNone(record['inputs']['stocks'][symbol]['result']['plan'])
        self.assertIn('순위 미확정', report)

    def test_collection_crossing_open_holds_only_late_symbols(self):
        source = UniverseResponses()
        current = [NOW]
        def fetch(url):
            body = source(url)
            if 'SYMB=MU' in url:
                current[0] = NOW + timedelta(hours=2)
            return body
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            record = u.run(out, DAY, fetch=fetch, clock=lambda: current[0], synthetic=True)
            self.assertEqual(record['result']['candidates'], [])
            self.assertIn('collection_outside_premarket', record['inputs']['stocks']['MU']['result']['reasons'])
            self.assertEqual(u.replay(out), record)

    def test_missing_list_entries_never_claim_complete_coverage(self):
        source = UniverseResponses()
        def fetch(url):
            body = source(url)
            query = parse_qs(urlparse(url).query)
            if '/stocks/all?' in url and query['market'] == ['NASDAQ'] and 'securityType' not in query:
                return json.dumps({'result': []})
            return body
        record, report = self.run_case(fetch)
        self.assertFalse(record['result']['coverage_complete'])
        self.assertEqual(record['result']['candidates'], ['MU'])
        self.assertEqual(record['result']['counts']['total'], 2)
        self.assertIn('전체 목록 범위: 미확보', report)

    def test_malformed_listing_preserves_verified_partition_and_record(self):
        source = UniverseResponses()
        def fetch(url):
            body = source(url)
            query = parse_qs(urlparse(url).query)
            if '/stocks/all?' in url and query['market'] == ['NASDAQ'] and 'securityType' not in query:
                data = json.loads(body)
                data['result'][0].pop('securityType')
                return json.dumps(data)
            return body
        try:
            record, _ = self.run_case(fetch)
        except KeyError:
            self.fail('Malformed listing must preserve a report and replayable record.')
        self.assertFalse(record['result']['coverage_complete'])
        self.assertEqual(record['result']['candidates'], ['MU'])

    def test_detail_omission_holds_that_symbol_without_erasing_other_results(self):
        source = UniverseResponses()
        def fetch(url):
            body = source(url)
            if urlparse(url).path == '/api/v1/stocks':
                return json.dumps({'result': [source.sources['MU'].stock]})
            return body
        record, _ = self.run_case(fetch)
        self.assertEqual(record['result']['candidates'], ['MU'])
        self.assertIn('stock_detail_missing', record['inputs']['stocks']['IBM']['result']['reasons'])

    def test_verified_no_candidates_and_all_held_are_distinct(self):
        source = UniverseResponses()
        source.sources['MU'].bars[-1]['tvol'] = '1400000'
        record, report = self.run_case(source)
        self.assertEqual(record['result']['status'], 'excluded')
        self.assertEqual(record['result']['counts']['excluded'], 1)
        self.assertIn('검증된 범위의 조건 충족 후보 없음', report)
        source.sources['MU'].earnings_note = 'The earnings announcement is tentative.'
        record, report = self.run_case(source)
        self.assertEqual(record['result']['status'], 'held')
        self.assertEqual(record['result']['counts']['held'], 2)
        self.assertIn('전체 평가 불가', report)

    def test_exchange_or_symbol_mismatch_is_held(self):
        source = UniverseResponses()
        def fetch(url):
            body = source(url)
            if '/dailyprice?' in url and 'SYMB=MU' in url:
                return body.replace('DNASMU', 'DNASOTHER')
            return body
        record, _ = self.run_case(fetch)
        self.assertEqual(record['result']['candidates'], [])
        self.assertIn('bars_0:price_identity_mismatch', record['inputs']['stocks']['MU']['result']['reasons'])

    def test_replay_rejects_modified_input_and_report_and_never_fetches(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            record = u.run(out, DAY, fetch=UniverseResponses(), now=NOW, synthetic=True)
            with patch('single_run.fetch_public', side_effect=AssertionError('network during replay')):
                self.assertEqual(u.replay(out), record)
            original = (out / 'report.md').read_text()
            (out / 'report.md').write_text(original + 'changed')
            with self.assertRaisesRegex(u.s.DataError, 'replay_report_mismatch'):
                u.replay(out)
            (out / 'report.md').write_text(original)
            record['responses'][0]['body'] = '{}'
            (out / 'record.json').write_text(json.dumps(record))
            with self.assertRaisesRegex(u.s.DataError, 'record_integrity_mismatch'):
                u.replay(out)

    def test_stock_all_requests_obey_separate_one_request_per_second_limit(self):
        from io import BytesIO
        with tempfile.TemporaryDirectory() as tmp:
            with patch('single_run.build_opener') as opener, patch('single_run.time.sleep') as sleep:
                opener.return_value.open.side_effect = lambda *a, **kw: BytesIO(b'{"result": []}')
                u.run(Path(tmp) / 'run', DAY, now=NOW,
                      fetch=lambda url: u.s.fetch_public(url, credentials={'TOSS_ACCESS_TOKEN': 'synthetic'}),
                      synthetic=True)
                self.assertGreaterEqual(sum(call.args[0] >= 1 for call in sleep.call_args_list), 6)


if __name__ == '__main__':
    unittest.main()
