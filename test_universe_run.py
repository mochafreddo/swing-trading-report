"""Exercise public-response collection through saved reports and offline replay."""

import json
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
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
    def test_initial_failures_preserve_per_stock_price_collection_and_replay(self):
        for mode, issues, prices, skipped in [
            ('stock', ['stock:source_fetch_failed', 'stock_detail_missing'], False, 'unverified_price_inputs'),
            ('calendar', ['calendar:source_fetch_failed'], False, 'unverified_session'),
            ('rejected', ['bars_0:price_identity_mismatch'], True, 'unverified_price_inputs'),
            ('null', [], True, 'unverified_price_inputs'),
        ]:
            with self.subTest(mode=mode):
                source = UniverseResponses()
                def fetch(url):
                    if (mode == 'stock' and '/api/v1/stocks?symbols=' in url
                            or mode == 'calendar' and '/market-calendar/' in url):
                        raise u.s.DataError('source_fetch_failed')
                    body = source(url)
                    if '/dailyprice?' in url and 'SYMB=MU' in url:
                        data = json.loads(body)
                        if mode == 'rejected':
                            data['rt_cd'] = '1'
                        elif mode == 'null':
                            data['output2'] = None
                        body = json.dumps(data)
                    return body
                record, _ = self.run_case(fetch)
                row = record['inputs']['stocks']['MU']
                self.assertEqual(row['inputs']['issues'], issues)
                self.assertEqual(row['result']['status'], 'held')
                self.assertEqual(row['inputs']['skipped'], {'earnings': skipped, 'turnover': skipped})
                urls = [item['url'] for item in record['responses']]
                self.assertEqual(any('/dailyprice?' in url and 'SYMB=MU' in url for url in urls), prices)
                self.assertEqual(any('/chart/MU?' in url for url in urls), prices)
                self.assertNotIn('bars_0', row['inputs'])
                if mode == 'null':
                    self.assertNotIn('invalid_required_data', row['result']['reasons'])

    def test_common_stock_evaluation_agrees_with_single_run(self):
        for mode in ('normal', 'small_cap', 'near_earnings', 'bad_prices'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                single = PublicResponses()
                universe = UniverseResponses()
                for source in (single, universe.sources['MU']):
                    if mode == 'small_cap':
                        source.stock['sharesOutstanding'] = '99999999'
                    elif mode == 'near_earnings':
                        source.earnings_day = 'September 10, 2026'
                    elif mode == 'bad_prices':
                        source.bars[-1]['open'] = '102'
                out = Path(tmp) / 'single'
                record = u.s.run(out, DAY, fetch=single, now=NOW, synthetic=True)
                self.assertEqual(u.s.replay(out), record)
                whole, _ = self.run_case(universe)
                row = whole['inputs']['stocks']['MU']
                self.assertEqual(row['result'], record['result'])
                self.assertEqual({key: value for key, value in row['inputs'].items() if key != 'collected_at'},
                                 record['inputs'])

    def test_repligen_archive_ignores_only_wholly_past_date_conflicts(self):
        for mode in ('past', 'future', 'mixed', 'later_announcement'):
            with self.subTest(mode=mode):
                source = UniverseResponses()
                source.add_company('RGEN', 2)
                def fetch(url):
                    if url == 'https://investors.repligen.com/press-releases/default.aspx':
                        return '<script src="/q4Api.js"></script>'
                    if urlparse(url).netloc == 'investors.repligen.com':
                        rows = []
                        if parse_qs(urlparse(url).query)['pageNumber'] == ['0']:
                            first = 'September 17, 2026' if mode == 'future' else 'July 28, 2026'
                            second = 'September 18, 2026' if mode in ('future', 'mixed') else 'August 6, 2026'
                            rows.append({'Headline': 'Repligen to Acquire BioLife Solutions',
                                         'PressReleaseDate': '07/22/2026 06:00:00',
                                         'LinkToDetailPage': '/press-releases/news-details/2026/acquisition/default.aspx',
                                         'Body': f'Repligen will report quarterly financial results on {first}. '
                                                 f'BioLife will report quarterly financial results on {second}.'})
                            if mode == 'later_announcement':
                                rows.append({'Headline': 'Repligen to Report Third Quarter Results',
                                             'PressReleaseDate': '09/01/2026 06:00:00',
                                             'LinkToDetailPage': '/press-releases/news-details/2026/results/default.aspx',
                                             'Body': 'Repligen will report quarterly financial results on September 17, 2026.'})
                        return json.dumps({'GetPressReleaseListResult': rows})
                    return source(url)
                record, _ = self.run_case(fetch)
                row = record['inputs']['stocks']['RGEN']
                event = row['inputs']['earnings']
                self.assertEqual(event['collection_status'], 'complete')
                if mode == 'later_announcement':
                    self.assertEqual(row['result']['status'], 'selected')
                    self.assertEqual(event['date'], '2026-09-17')
                else:
                    self.assertEqual(row['result']['status'], 'held')
                    self.assertEqual(event['reason'], 'next_confirmed_earnings_not_found' if mode == 'past'
                                     else 'earnings_dates_conflict')

    def test_embedded_issuer_calendar_is_collected_without_treating_calls_as_releases(self):
        from html import escape
        for mode in ('past', 'past_utc', 'unrelated_invalid_date', 'future_call', 'invalid_date', 'partial', 'empty'):
            with self.subTest(mode=mode):
                source = UniverseResponses()
                source.add_company('AAA', 2)
                config = source.earnings_sources['AAA']
                def fetch(url):
                    if url == config['listing_url']:
                        event = {'EventType': 'Earnings', 'EventName': 'AAA Corporation Earnings Conference Call',
                                 'DateTime': {'UTC': '2026-08-20T21:30:00'}}
                        if mode == 'future_call':
                            event['DateTime']['UTC'] = '2026-09-17T21:30:00'
                        elif mode == 'past_utc':
                            event['DateTime']['UTC'] += 'Z'
                        elif mode == 'invalid_date':
                            event['DateTime']['UTC'] = 'unknown'
                        data = {'Events': [] if mode == 'empty' else [event]}
                        if mode == 'unrelated_invalid_date':
                            data['Events'].append({'EventType': 'Conferences', 'EventName': 'Technology conference',
                                                   'DateTime': {'UTC': '2024-08-06:00:00:00'}})
                        section = 'recent' if mode == 'partial' else 'all'
                        return ('<cascade-events-render-component eventssection="' + section + '" eventsdata="'
                                + escape(json.dumps(data), quote=True) + '"></cascade-events-render-component>'
                                + '<nav><a href="' + config['article_prefix'] + 'leadership">Leadership</a></nav>')
                    if url.endswith('/leadership'):
                        raise u.s.DataError('http_301')
                    return source(url)
                record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
                row = record['inputs']['stocks']['AAA']
                self.assertEqual(row['result']['status'], 'held')
                self.assertIsNone(row['result']['plan'])
                event = row['inputs']['earnings']
                if mode in ('past', 'past_utc', 'unrelated_invalid_date'):
                    self.assertEqual(event['reason'], 'next_confirmed_earnings_not_found')
                    self.assertEqual(event['collection_status'], 'complete')
                    self.assertEqual(event['observed_events'], 2 if mode == 'unrelated_invalid_date' else 1)
                elif mode == 'future_call':
                    self.assertEqual(event['reason'], 'earnings_event_requires_release_announcement')
                    self.assertEqual(event['collection_status'], 'unsupported')
                else:
                    self.assertNotEqual(event.get('collection_status'), 'complete')
                self.assertFalse(any(item['url'].endswith('/leadership') for item in record['responses']))

    def test_ir_article_name_and_local_publication_time_preserve_confirmed_release(self):
        source = UniverseResponses()
        source.add_company('AAA', 2)
        article_url = source.earnings_sources['AAA']['article_prefix'] + 'release'
        for mode in ('name', 'both', 'passive', 'same_day', 'postponed', 'conflicting'):
            with self.subTest(mode=mode):
                def fetch(url):
                    if url == article_url:
                        body = 'AAA Corporation will publish quarterly financial results on Thursday, September 17, 2026.'
                        if mode == 'passive':
                            body = 'Quarterly financial results will be published on Thursday, September 17, 2026.'
                        if mode == 'postponed':
                            body += ' The earnings announcement has been postponed.'
                        article = {'@type': 'Article', 'name': 'AAA Corporation Announces Earnings Schedule',
                                   'datePublished': '2026-09-10T08:00:00' if mode == 'same_day' else '2026-09-01T13:08:22',
                                   'articleBody': body}
                        articles = [article]
                        if mode in ('both', 'conflicting'):
                            articles.insert(0, {'@type': 'Article', 'headline': article['name'],
                                                'datePublished': '2026-09-01T20:08:22Z',
                                                'articleBody': body.replace('17', '18') if mode == 'conflicting' else body})
                        return ''.join('<script type="application/ld+json">' + json.dumps(item) + '</script>'
                                       for item in articles)
                    return source(url)
                record, report = self.run_case(fetch, earnings_sources=source.earnings_sources)
                row = record['inputs']['stocks']['AAA']
                if mode in ('same_day', 'postponed', 'conflicting'):
                    self.assertEqual(row['result']['status'], 'held')
                    self.assertIsNone(row['result']['plan'])
                else:
                    self.assertEqual(row['result']['status'], 'selected')
                    self.assertEqual(row['inputs']['earnings']['date'], '2026-09-17')
                    self.assertIn(article_url, report)

    def test_production_ir_probe_preserves_page_split_errors_and_replays(self):
        import probe_earnings_sources as probe
        source = {'company': 'AAA Corporation', 'listing_url': 'https://ir.example.com/AAA',
                  'article_prefix': 'https://ir.example.com/releases/AAA/'}
        for failure in ('split', 'single_item_too_large', 'http_403'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                def fetch(url, **kwargs):
                    if url == source['listing_url']:
                        return '<script src="/q4Api.js"></script>'
                    query = parse_qs(urlparse(url).query)
                    if failure == 'http_403':
                        raise u.s.DataError('http_403')
                    if query['pageSize'] == ['5'] or failure == 'single_item_too_large':
                        raise u.s.DataError('response_too_large')
                    rows = [] if query['pageNumber'] != ['0'] else [{
                        'Headline': 'AAA Corporation Earnings Schedule', 'PressReleaseDate': '09/01/2026 12:00:00',
                        'LinkToDetailPage': '/releases/AAA/release',
                        'Body': '<p>AAA Corporation will release financial results on September 17, 2026.</p>'}]
                    return json.dumps({'GetPressReleaseListResult': rows})
                output = Path(tmp) / 'probe'
                with patch.object(probe, 'SOURCES', [('AAA', 'AAA Corporation', source['listing_url'], ('ir.example.com',))]), \
                        patch.dict(u.DEFAULT_EARNINGS_SOURCES, {'AAA': source}), \
                        patch.object(probe, 'datetime', wraps=probe.datetime) as clock, \
                        patch.object(probe.time, 'sleep'), redirect_stdout(StringIO()):
                    clock.now.return_value = NOW
                    with patch('sys.argv', ['probe', '--production', '--output', str(output)]), \
                            patch.object(u.s, 'fetch_public', side_effect=fetch):
                        probe.main()
                    record = json.loads((output / 'record.json').read_text())
                    event = record['results'][0]['event']
                    if failure == 'split':
                        self.assertEqual(event['status'], 'confirmed')
                        self.assertEqual(event['date'], '2026-09-17')
                    else:
                        self.assertEqual(event['collection_status'], 'failed')
                    self.assertEqual(len(record['requests']), {'split': 4, 'single_item_too_large': 3, 'http_403': 2}[failure])
                    with patch('sys.argv', ['probe', '--replay', str(output)]), \
                            patch.object(u.s, 'fetch_public', side_effect=AssertionError('network during replay')):
                        probe.main()

    def test_reviewed_non_common_security_resolves_only_its_listing_conflict(self):
        source = UniverseResponses()
        source.add_company('AAA', 2)
        source.sources['AAA'].stock.update(isinCode='US0000000001', englishName='AAA WARRANTS')
        evidence_url = 'https://ir.example.com/securities/AAA'
        evidence = {'market': 'NASDAQ', 'isin': 'US0000000001', 'english_name': 'AAA WARRANTS',
                    'reviewed_on': '2026-09-01', 'classification': 'warrant', 'source': evidence_url,
                    'required_text': ['AAA warrants (CUSIP 000000000)']}
        def fetch(url):
            if url == evidence_url:
                return '<p>AAA warrants (CUSIP 000000000) are exercisable into common stock.</p>'
            body = source(url)
            query = parse_qs(urlparse(url).query)
            if '/stocks/all?' in url and 'securityType' in query:
                data = json.loads(body)
                data['result'] = [row for row in data['result'] if row['symbol'] != 'AAA']
                return json.dumps(data)
            return body
        with patch('universe_run.REVIEWED_NON_COMMON', {'AAA': evidence}, create=True):
            record, report = self.run_case(fetch, earnings_sources=source.earnings_sources)
        row = record['inputs']['stocks']['AAA']
        self.assertEqual(row['result']['status'], 'excluded')
        self.assertEqual(row['result']['reasons'], ['verified_non_common_security'])
        self.assertEqual(row['inputs']['stock_detail']['securityType'], 'STOCK')
        self.assertEqual(row['inputs']['security_classification']['classification'], 'warrant')
        self.assertEqual(set(row['inputs']['skipped']), {'prices', 'earnings', 'turnover'})
        self.assertTrue(record['result']['coverage_complete'])
        self.assertEqual(record['result']['candidates'], ['MU'])
        self.assertIn('AAA', record['inputs']['universe']['markets']['NASDAQ']['conflicts'])
        self.assertIn('NASDAQ:list_coverage_mismatch', record['inputs']['universe']['issues'])
        self.assertIn(evidence_url, report)
        self.assertFalse(any('SYMB=AAA' in item['url'] or '/chart/AAA' in item['url']
                             or '/releases/AAA/' in item['url'] for item in record['responses']))

        for quotes in source.sources.values():
            quotes.days.remove(DAY)
        with patch('universe_run.REVIEWED_NON_COMMON', {'AAA': evidence}):
            closed_record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
        self.assertEqual(closed_record['result']['status'], 'held')
        self.assertEqual(closed_record['result']['counts'], {'total': 3, 'selected': 0, 'excluded': 1, 'held': 2})
        self.assertTrue(closed_record['result']['coverage_complete'])

    def test_reviewed_pdf_requires_exact_bytes_and_replays_without_network(self):
        import base64
        import hashlib
        from io import BytesIO
        pdf = b'%PDF-1.7\n%\xe2\xe3\xcf\xd3\nreviewed synthetic rights notice\n%%EOF'
        encoded = 'data:application/pdf;base64,' + base64.b64encode(pdf).decode('ascii')
        for mode in ('matching', 'changed', 'html_error'):
            with self.subTest(mode=mode):
                source = UniverseResponses()
                source.add_company('AAA', 2)
                source.sources['AAA'].stock.update(isinCode='US0000000001', englishName='AAA RIGHTS')
                url = 'https://ir.example.com/rights.pdf'
                evidence = {'market': 'NASDAQ', 'isin': 'US0000000001', 'english_name': 'AAA RIGHTS',
                            'reviewed_on': '2026-09-01', 'classification': 'subscription_right', 'source': url,
                            'required_body_sha256': hashlib.sha256(encoded.encode()).hexdigest()}
                class Http:
                    def open(self, request, timeout):
                        if request.full_url == url:
                            return BytesIO(pdf if mode == 'matching' else pdf + b'changed' if mode == 'changed'
                                           else b'<p>Access denied</p>')
                        body = source(request.full_url)
                        query = parse_qs(urlparse(request.full_url).query)
                        if '/stocks/all?' in request.full_url and 'securityType' in query:
                            data = json.loads(body)
                            data['result'] = [row for row in data['result'] if row['symbol'] != 'AAA']
                            body = json.dumps(data)
                        return BytesIO(body.encode())
                credentials = dict.fromkeys(('TOSS_ACCESS_TOKEN', 'KIS_ACCESS_TOKEN', 'KIS_APP_KEY',
                                             'KIS_APP_SECRET'), 'synthetic')
                with patch('universe_run.REVIEWED_NON_COMMON', {'AAA': evidence}), \
                     patch('single_run.build_opener', return_value=Http()), patch('single_run.time.sleep'):
                    record, report = self.run_case(
                        lambda link: u.s.fetch_public(link, credentials=credentials, public_hosts=('ir.example.com',)),
                        earnings_sources=source.earnings_sources)
                row = record['inputs']['stocks']['AAA']
                self.assertEqual(row['result']['status'], 'excluded' if mode == 'matching' else 'held')
                self.assertEqual(record['result']['coverage_complete'], mode == 'matching')
                if mode == 'matching':
                    self.assertIn(url, report)
                    saved = next(item for item in record['responses'] if item['url'] == url)
                    self.assertEqual(base64.b64decode(saved['body'].split(',', 1)[1]), pdf)
                    self.assertIn('AAA', record['inputs']['universe']['markets']['NASDAQ']['conflicts'])
                else:
                    self.assertIn('security_classification:security_classification_evidence_missing',
                                  row['inputs']['issues'])

    def test_non_common_review_cannot_hide_missing_identity_evidence_or_other_listings(self):
        for mode in ('detail_isin', 'list_isin', 'name', 'market', 'ambiguous', 'missing_detail',
                     'missing_evidence', 'http_failure', 'future_review', 'other_conflict', 'empty_list'):
            with self.subTest(mode=mode):
                source = UniverseResponses()
                source.add_company('AAA', 2)
                source.sources['AAA'].stock.update(isinCode='US0000000001', englishName='AAA WARRANTS')
                evidence_url = 'https://ir.example.com/securities/AAA'
                evidence = {'market': 'NASDAQ', 'isin': 'US0000000001', 'english_name': 'AAA WARRANTS',
                            'reviewed_on': '2026-09-11' if mode == 'future_review' else '2026-09-01',
                            'classification': 'warrant', 'source': evidence_url,
                            'required_text': ['AAA warrants (CUSIP 000000000)']}
                def fetch(url):
                    if url == evidence_url:
                        if mode == 'http_failure':
                            raise u.s.DataError('http_403')
                        return '<p>Unrelated notice.</p>' if mode == 'missing_evidence' else '<p>AAA warrants (CUSIP 000000000)</p>'
                    body = source(url)
                    query = parse_qs(urlparse(url).query)
                    if '/stocks/all?' in url:
                        data = json.loads(body)
                        if 'securityType' in query:
                            data['result'] = [row for row in data['result'] if row['symbol'] != 'AAA'
                                              and not (mode == 'other_conflict' and row['symbol'] == 'MU')]
                        elif mode == 'empty_list' and query['market'] == ['NASDAQ']:
                            data['result'] = []
                        elif mode == 'list_isin':
                            for row in data['result']:
                                if row['symbol'] == 'AAA':
                                    row['isinCode'] = 'US0000000002'
                        elif mode == 'ambiguous' and query['market'] == ['NYSE']:
                            data['result'].append(source.sources['AAA'].stock)
                        return json.dumps(data)
                    if urlparse(url).path == '/api/v1/stocks':
                        data = json.loads(body)
                        if mode == 'missing_detail':
                            data['result'] = [row for row in data['result'] if row['symbol'] != 'AAA']
                        for row in data['result']:
                            if row['symbol'] == 'AAA':
                                if mode == 'detail_isin':
                                    row['isinCode'] = 'US0000000002'
                                elif mode == 'name':
                                    row['englishName'] = 'AAA COMMON STOCK'
                                elif mode == 'market':
                                    row['market'] = 'NYSE'
                        return json.dumps(data)
                    return body
                with patch('universe_run.REVIEWED_NON_COMMON', {'AAA': evidence}):
                    record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
                self.assertFalse(record['result']['coverage_complete'])
                if mode not in ('other_conflict', 'empty_list'):
                    self.assertEqual(record['inputs']['stocks']['AAA']['result']['status'], 'held')
                    self.assertEqual(record['result']['candidates'], ['MU'])
                else:
                    self.assertEqual(record['inputs']['stocks']['MU']['result']['status'], 'held')
                self.assertNotIn('AAA', record['result']['candidates'])

    def test_ir_page_split_does_not_hide_single_item_or_http_failures(self):
        for failure in ('response_too_large', 'http_403'):
            with self.subTest(failure=failure):
                source = UniverseResponses()
                source.add_company('AAA', 2)
                config = source.earnings_sources['AAA']
                def fetch(url):
                    if url == config['listing_url']:
                        return '<script src="/q4Api.js"></script>'
                    if '/feed/PressRelease.svc/' in url:
                        raise u.s.DataError(failure)
                    return source(url)
                record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
                row = record['inputs']['stocks']['AAA']
                self.assertEqual(row['result']['status'], 'held')
                self.assertEqual(row['inputs']['earnings']['collection_status'], 'failed')
                self.assertEqual(row['inputs']['earnings']['reason'], failure)
                requests = [entry for entry in record['responses'] if '/feed/PressRelease.svc/' in entry['url']]
                self.assertEqual(len(requests), 2 if failure == 'response_too_large' else 1)

    def test_oversized_ir_page_resumes_at_same_offset_with_full_bodies(self):
        source = UniverseResponses()
        source.add_company('AAA', 2)
        config = source.earnings_sources['AAA']
        rows = [{'Headline': 'AAA Corporation Product Update',
                 'PressReleaseDate': '09/01/2026 12:00:00',
                 'LinkToDetailPage': '/releases/AAA/' + str(index), 'Body': '<p>Product news</p>'}
                for index in range(8)]
        rows[6].update(Headline='AAA Corporation Earnings Schedule',
                       Body='<p>AAA Corporation will release financial results on September 17, 2026.</p>')
        def fetch(url):
            if url == config['listing_url']:
                return '<script src="/q4Api.js"></script>'
            if '/feed/PressRelease.svc/' in url:
                query = parse_qs(urlparse(url).query)
                page, size = int(query['pageNumber'][0]), int(query['pageSize'][0])
                if page == 1 and size == 5:
                    raise u.s.DataError('response_too_large')
                return json.dumps({'GetPressReleaseListResult': rows[page * size:(page + 1) * size]})
            return source(url)
        record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
        row = record['inputs']['stocks']['AAA']
        self.assertEqual(row['result']['status'], 'selected')
        self.assertEqual(row['inputs']['earnings']['date'], '2026-09-17')
        self.assertIn('pageNumber=6&pageSize=1', row['inputs']['earnings']['evidence_url'])

    def test_ir_navigation_root_and_next_page_are_not_articles(self):
        source = UniverseResponses()
        source.add_company('AAA', 2)
        config = source.earnings_sources['AAA']
        next_url = config['article_prefix'] + '?page=2'
        def fetch(url):
            if url == config['listing_url']:
                return ('<a href="/releases/AAA/">News home</a>'
                        '<a rel="next" href="/releases/AAA/?page=2">Next</a>')
            if url == next_url:
                return '<a href="/releases/AAA/release">Earnings</a>'
            if url == config['article_prefix']:
                return '<h1>News</h1>'
            return source(url)
        record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
        row = record['inputs']['stocks']['AAA']
        self.assertEqual(row['result']['status'], 'selected')
        self.assertEqual(row['inputs']['earnings']['source'], config['article_prefix'] + 'release')

    def test_head_next_link_cannot_hide_a_later_earnings_postponement(self):
        source = UniverseResponses()
        source.add_company('AAA', 2)
        config = source.earnings_sources['AAA']
        def fetch(url):
            if url == config['listing_url']:
                return ('<link rel="next" href="/AAA?page=2">'
                        '<a href="/releases/AAA/release">Earnings</a>')
            if url == 'https://ir.example.com/AAA?page=2':
                return '<a href="/releases/AAA/change">Updated schedule</a>'
            if url == config['article_prefix'] + 'change':
                return '<script type="application/ld+json">' + json.dumps({
                    '@type': 'NewsArticle', 'headline': 'AAA Corporation Earnings Update',
                    'datePublished': '2026-09-09T12:00:00Z',
                    'articleBody': 'The earnings announcement has been postponed.'}) + '</script>'
            return source(url)
        record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
        row = record['inputs']['stocks']['AAA']
        self.assertEqual(row['result']['status'], 'held')
        self.assertEqual(row['inputs']['earnings']['reason'], 'earnings_schedule_changed')

    def test_uncertain_ir_evidence_never_selects_a_candidate(self):
        for mode in ('call_only', 'wrong_company', 'same_day_unknown_time', 'cycle', 'changed_schedule'):
            with self.subTest(mode=mode):
                source = UniverseResponses()
                source.add_company('AAA', 2)
                config = source.earnings_sources['AAA']
                def fetch(url):
                    if url == config['listing_url'] and mode == 'cycle':
                        return '<a href="/releases/AAA/release">Earnings</a><a rel="next" href="/AAA">Next</a>'
                    if url == config['article_prefix'] + 'release':
                        body = 'AAA Corporation will release financial results on September 17, 2026.'
                        title = 'AAA Corporation Announces Earnings Schedule'
                        published = '2026-09-01T12:00:00Z'
                        if mode == 'call_only':
                            body = 'AAA Corporation will host a conference call on September 17, 2026 to discuss earnings.'
                        if mode == 'wrong_company':
                            title, body = title.replace('AAA', 'OTHER'), body.replace('AAA', 'OTHER')
                        if mode == 'same_day_unknown_time':
                            published = '2026-09-10'
                        if mode == 'changed_schedule':
                            body += ' The earnings announcement has been postponed.'
                        return '<script type="application/ld+json">' + json.dumps({
                            '@type': 'NewsArticle', 'headline': title,
                            'datePublished': published, 'articleBody': body}) + '</script>'
                    return source(url)
                record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
                row = record['inputs']['stocks']['AAA']
                self.assertEqual(row['result']['status'], 'held')
                self.assertIsNone(row['result']['plan'])

    def test_ir_uses_release_date_not_fiscal_period_end_or_forward_looking_boilerplate(self):
        source = UniverseResponses()
        source.add_company('AAA', 2)
        article_url = source.earnings_sources['AAA']['article_prefix'] + 'release'
        def fetch(url):
            if url == article_url:
                return '<script type="application/ld+json">' + json.dumps({
                    '@type': 'NewsArticle', 'headline': 'AAA Corporation Announces Earnings Schedule',
                    'datePublished': '2026-09-01T12:00:00Z',
                    'articleBody': 'AAA Corporation will release financial results for the quarter ended August 31, 2026 on Thursday, September 17, 2026. '
                                   'Forward-looking statements describe expected market growth.'}) + '</script>'
            return source(url)
        record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
        row = record['inputs']['stocks']['AAA']
        self.assertEqual(row['result']['status'], 'selected')
        self.assertEqual(row['inputs']['earnings']['date'], '2026-09-17')

    def test_ir_fetch_failure_is_distinct_from_completed_search_without_evidence(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                source = UniverseResponses()
                source.add_company('AAA', 2)
                url = source.earnings_sources['AAA']['listing_url']
                def fetch(target):
                    if target == url:
                        if failed:
                            raise u.s.DataError('http_403')
                        return '<a href="/releases/AAA/history">Quarterly Results</a>'
                    if target.endswith('/releases/AAA/history'):
                        return '<script type="application/ld+json">' + json.dumps({
                            '@type': 'NewsArticle', 'headline': 'AAA Corporation Reports Quarterly Results',
                            'datePublished': '2026-08-01T12:00:00Z'}) + '</script>'
                    return source(target)
                record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
                row = record['inputs']['stocks']['AAA']
                self.assertEqual(row['result']['status'], 'held')
                event = row['inputs']['earnings']
                self.assertEqual(event['collection_status'], 'failed' if failed else 'complete')
                self.assertEqual(event['reason'], 'http_403' if failed else 'next_confirmed_earnings_not_found')

    def test_unhandled_dynamic_listing_is_not_a_completed_empty_search(self):
        source = UniverseResponses()
        source.add_company('AAA', 2)
        def fetch(url):
            if url == source.earnings_sources['AAA']['listing_url']:
                return '<div id="news"></div><script src="/custom-dynamic-news.js"></script>'
            return source(url)
        record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
        event = record['inputs']['stocks']['AAA']['inputs']['earnings']
        self.assertEqual(event['collection_status'], 'unsupported')
        self.assertEqual(event['reason'], 'no_supported_listing_items')

    def test_listing_conflicts_are_preserved_per_symbol_for_reconciliation(self):
        source = UniverseResponses()
        source.add_company('AAA', 3)
        def fetch(url):
            body = source(url)
            query = parse_qs(urlparse(url).query)
            if '/stocks/all?' in url and query.get('market') == ['NASDAQ'] and query.get('securityType') == ['STOCK']:
                return json.dumps({'result': [row for row in json.loads(body)['result'] if row['symbol'] != 'MU']})
            return body
        record, report = self.run_case(fetch, earnings_sources=source.earnings_sources)
        self.assertFalse(record['result']['coverage_complete'])
        conflict = record['inputs']['universe']['markets']['NASDAQ']['conflicts']['MU']
        self.assertEqual(conflict['reason'], 'general_only')
        self.assertEqual(conflict['general']['symbol'], 'MU')
        self.assertEqual(conflict['typed'], [])
        self.assertIn('MU', report)
        self.assertEqual(record['inputs']['stocks']['MU']['result']['status'], 'held')
        self.assertIn('stock_listing_conflict', record['inputs']['stocks']['MU']['result']['reasons'])
        self.assertEqual(record['result']['candidates'], ['AAA'])

    def test_dynamic_ir_feed_preserves_publication_precision_and_official_evidence(self):
        source = UniverseResponses()
        source.add_company('AAA', 2)
        config = source.earnings_sources['AAA']
        def fetch(url):
            if url == config['listing_url']:
                return '<script src="/js/evergreen.q4Api.min.js"></script><script>q4News({category:"abc"})</script>'
            if '/feed/PressRelease.svc/GetPressReleaseList?' in url:
                if parse_qs(urlparse(url).query)['pageNumber'] != ['0']:
                    return json.dumps({'GetPressReleaseListResult': []})
                return json.dumps({'GetPressReleaseListResult': [{
                    'Headline': 'AAA Corporation to Announce Quarterly Results',
                    'PressReleaseDate': '09/01/2026 16:05:00',
                    'LinkToDetailPage': '/releases/AAA/release',
                    'Body': '<p>AAA Corporation financial results will be released on September 17th, 2026.</p>'}]})
            return source(url)
        record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
        event = record['inputs']['stocks']['AAA']['inputs']['earnings']
        self.assertEqual(event['status'], 'confirmed')
        self.assertEqual(event['date'], '2026-09-17')
        self.assertEqual(event['publication_precision'], 'date')
        self.assertEqual(event['published_at'], '2026-09-01')
        self.assertIn('/feed/PressRelease.svc/', event['evidence_url'])

    def test_ir_body_qualifications_changes_and_call_dates_cannot_confirm_an_event(self):
        for mode in ('tentative_title', 'tentative_body', 'expected_body', 'conflicting_body', 'call_clause', 'generic_change_title', 'html_conflict', 'html_tentative', 'fiscal_ending_on', 'fiscal_ending_ordinal', 'fiscal_ending_weekday'):
            with self.subTest(mode=mode):
                source = UniverseResponses()
                source.add_company('AAA', 2)
                config = source.earnings_sources['AAA']
                def fetch(url):
                    if url == config['listing_url']:
                        return '<a href="/releases/AAA/release">Earnings</a>' + (
                            '<a href="/releases/AAA/update">Update</a>' if mode == 'generic_change_title' else '')
                    if url.startswith(config['article_prefix']):
                        title = 'AAA Corporation to Report Fiscal Fourth Quarter Results on September 17, 2026'
                        body = 'AAA Corporation will release financial results on September 17, 2026.'
                        published = '2026-09-01T12:00:00Z'
                        if mode == 'tentative_title':
                            body += ' The date is tentative.'
                        elif mode == 'expected_body':
                            body = 'AAA Corporation is expected to report financial results on September 17, 2026.'
                        elif mode == 'conflicting_body':
                            body = 'AAA Corporation will release financial results on September 11, 2026.'
                        elif mode == 'tentative_body':
                            title = 'AAA Corporation Announces Earnings Schedule'
                            body += ' This date is tentative.'
                        elif mode == 'call_clause':
                            title = 'AAA Corporation Announces Earnings Schedule'
                            body = 'AAA Corporation will release financial results after market close and host a conference call on September 17, 2026.'
                        elif url.endswith('update'):
                            title = 'AAA Corporation Updates Announcement Date'
                            body = 'AAA Corporation has rescheduled financial results from September 17, 2026 to September 24, 2026.'
                            published = '2026-09-02T12:00:00Z'
                        html = ''
                        if mode == 'html_conflict':
                            html = '<p>AAA Corporation will release financial results on September 11, 2026.</p>'
                        elif mode == 'html_tentative':
                            html = '<p>This earnings date is tentative.</p>'
                        elif mode.startswith('fiscal_ending'):
                            title = 'AAA Corporation Announces Earnings Schedule'
                            body = 'AAA Corporation will report financial results for the quarter ending on ' + {
                                'fiscal_ending_on': 'September 30, 2026.',
                                'fiscal_ending_ordinal': 'September 30th, 2026.',
                                'fiscal_ending_weekday': 'Wednesday, September 30, 2026.'}[mode]
                        return '<script type="application/ld+json">' + json.dumps({
                            '@type': 'NewsArticle', 'headline': title, 'datePublished': published, 'articleBody': body}) + '</script>' + html
                    return source(url)
                record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
                row = record['inputs']['stocks']['AAA']
                self.assertEqual(row['result']['status'], 'held')
                self.assertIsNone(row['result']['plan'])

    def test_conflicting_future_ir_announcements_do_not_choose_an_arbitrary_date(self):
        source = UniverseResponses()
        source.add_company('AAA', 2)
        config = source.earnings_sources['AAA']
        def fetch(url):
            if url == config['listing_url']:
                return '<a href="/releases/AAA/one">Earnings</a><a href="/releases/AAA/two">Earnings</a>'
            if url in (config['article_prefix'] + 'one', config['article_prefix'] + 'two'):
                day = '17' if url.endswith('one') else '18'
                return '<script type="application/ld+json">' + json.dumps({
                    '@type': 'NewsArticle', 'headline': 'AAA Corporation to Announce Quarterly Results',
                    'datePublished': '2026-09-01T12:00:00Z',
                    'articleBody': 'AAA Corporation will release financial results on September ' + day + ', 2026.'}) + '</script>'
            return source(url)
        record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
        row = record['inputs']['stocks']['AAA']
        self.assertEqual(row['result']['status'], 'held')
        self.assertEqual(row['inputs']['earnings']['reason'], 'earnings_dates_conflict')

    def test_dynamic_ir_repeated_page_is_a_failed_collection(self):
        source = UniverseResponses()
        source.add_company('AAA', 2)
        config = source.earnings_sources['AAA']
        def fetch(url):
            if url == config['listing_url']:
                return '<script src="/q4Api.js"></script>'
            if '/feed/PressRelease.svc/' in url:
                return json.dumps({'GetPressReleaseListResult': [{
                    'Headline': 'AAA Corporation to Announce Quarterly Results',
                    'PressReleaseDate': '09/01/2026 16:05:00', 'LinkToDetailPage': '/releases/AAA/release',
                    'Body': 'AAA Corporation will release earnings on September 17, 2026.'}]})
            return source(url)
        record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
        row = record['inputs']['stocks']['AAA']
        self.assertEqual(row['result']['status'], 'held')
        self.assertEqual(row['inputs']['earnings']['reason'], 'earnings_feed_did_not_progress')
        self.assertEqual(row['inputs']['earnings']['collection_status'], 'failed')

    def test_dynamic_ir_walks_short_pages_until_explicit_empty_page(self):
        source = UniverseResponses()
        source.add_company('AAA', 2)
        config = source.earnings_sources['AAA']
        def fetch(url):
            if url == config['listing_url']:
                return '<script src="/js/evergreen.q4Api.min.js"></script>'
            if '/feed/PressRelease.svc/GetPressReleaseList?' in url:
                number = int(parse_qs(urlparse(url).query)['pageNumber'][0])
                rows = [] if number > 1 else [{
                    'Headline': 'AAA Corporation to Announce Quarterly Results',
                    'PressReleaseDate': '09/01/2026 16:05:00',
                    'LinkToDetailPage': '/releases/AAA/' + str(number),
                    'Body': 'AAA Corporation will release financial results on ' +
                            ('August 17, 2026.' if number == 0 else 'September 17, 2026.')}]
                return json.dumps({'GetPressReleaseListResult': rows})
            return source(url)
        record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
        event = record['inputs']['stocks']['AAA']['inputs']['earnings']
        self.assertEqual(event['status'], 'confirmed')
        self.assertEqual(event['date'], '2026-09-17')
        self.assertIn('pageNumber=1', event['evidence_url'])
        self.assertTrue(any('pageNumber=2' in r['url'] for r in record['responses']))

    def test_paginated_relative_ir_links_and_release_date_distinct_from_call(self):
        source = UniverseResponses()
        source.add_company('AAA', 2)
        config = source.earnings_sources['AAA']
        article_url = config['article_prefix'] + 'release'
        def fetch(url):
            if url == config['listing_url']:
                return '<a rel="next" href="/AAA?page=2">Next</a>'
            if url == 'https://ir.example.com/AAA?page=2':
                return '<a href="/releases/AAA/release">AAA Corporation earnings schedule</a>'
            if url == article_url:
                return '<script type="application/ld+json">' + json.dumps({'@graph': [{
                    '@type': 'NewsArticle', 'headline': 'AAA Corporation Announces Earnings Schedule',
                    'datePublished': '2026-09-01T12:00:00Z',
                    'articleBody': 'AAA Corporation will release financial results on September 17, 2026. '
                                   'The conference call will be held on September 18, 2026.'}]}) + '</script>'
            return source(url)
        record, _ = self.run_case(fetch, earnings_sources=source.earnings_sources)
        row = record['inputs']['stocks']['AAA']
        self.assertEqual(row['result']['status'], 'selected')
        self.assertEqual(row['inputs']['earnings']['date'], '2026-09-17')
        self.assertEqual(row['inputs']['earnings']['source'], article_url)
        self.assertEqual(row['inputs']['earnings']['collection_status'], 'complete')

    def test_verified_exclusion_skips_earnings_and_turnover_and_replays(self):
        source = UniverseResponses()
        source.sources['IBM'].stock['sharesOutstanding'] = '99999999'
        source.sources['MU'].bars[-1]['tvol'] = '1400000'
        record, report = self.run_case(source)
        self.assertEqual(record['result']['counts'], {'total': 2, 'selected': 0, 'excluded': 2, 'held': 0})
        for symbol, reason in [('IBM', 'market_cap_below_minimum'), ('MU', 'volume_below_multiple')]:
            row = record['inputs']['stocks'][symbol]
            self.assertIn(reason, row['result']['reasons'])
            self.assertEqual(row['inputs']['skipped'], {'earnings': 'verified_exclusion', 'turnover': 'verified_exclusion'})
            self.assertIsNone(row['result']['plan'])
            self.assertNotIn('turnover', row['inputs'])
        urls = [item['url'] for item in record['responses']]
        self.assertFalse(any('inquire-time-itemchartprice' in url or 'micron.com' in url for url in urls))
        self.assertIn('실적 일정 조회 생략 2종목', report)
        self.assertIn('거래대금 조회 생략 2종목', report)

    def test_unverified_prices_or_identity_cannot_prove_small_cap_exclusion(self):
        for mode in ('price', 'split', 'identity', 'late'):
            with self.subTest(mode=mode):
                source = UniverseResponses()
                source.sources['MU'].stock['sharesOutstanding'] = '1'
                if mode == 'price':
                    def mismatch(data):
                        data['indicators']['quote'][0]['high'][0] = '120'
                        return data
                    source.sources['MU'].reference_edit = mismatch
                if mode == 'split':
                    source.sources['MU'].splits = {'event': {'date': int(NOW.timestamp()), 'numerator': 2, 'denominator': 1}}
                current = [NOW]
                def fetch(url):
                    body = source(url)
                    if '/dailyprice?' in url and 'SYMB=MU' in url:
                        if mode == 'identity':
                            return body.replace('DNASMU', 'DNASOTHER')
                        if mode == 'late':
                            current[0] = NOW + timedelta(hours=2)
                    return body
                record, _ = self.run_case(fetch, clock=lambda: current[0])
                row = record['inputs']['stocks']['MU']
                self.assertEqual(row['result']['status'], 'held')
                self.assertNotIn('market_cap_below_minimum', row['result']['reasons'])
                self.assertIsNone(row['result']['plan'])


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

    def test_unknown_earnings_after_price_validation_skips_turnover(self):
        source = UniverseResponses()
        requested = []
        def fetch(url):
            requested.append(url)
            return source(url)
        record, report = self.run_case(fetch)
        self.assertEqual(record['result']['candidates'], ['MU'])
        self.assertEqual(record['result']['counts']['total'], 2)
        self.assertEqual(record['result']['collection_skipped']['turnover'], 1)
        self.assertIn('거래대금 조회 생략 1종목', report)
        self.assertTrue(any('/chart/IBM?' in url for url in requested))
        self.assertFalse(any('inquire-time-itemchartprice' in url and 'SYMB=IBM' in url for url in requested))
        self.assertEqual(record['inputs']['stocks']['IBM']['inputs']['skipped'],
                         {'earnings': 'source_not_configured', 'turnover': 'unverified_earnings'})

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

    def test_ranking_preserves_collected_inputs_and_repeats_final_decisions(self):
        inputs = {'universe': {'issues': [], 'markets': {}}, 'stocks': {
            symbol: {'inputs': {}, 'result': {
                'status': 'selected', 'reasons': ['all_conditions_met'],
                'metrics': {'volume_ratio': ratio}, 'plan': {'entry_low': '100'}}}
            for symbol, ratio in [('AAA', '2'), ('BBB', '2.0'), ('CCC', '3')]}}
        original = deepcopy(inputs)

        first = u.finalize(inputs)
        self.assertEqual(inputs, original)
        self.assertEqual(u.finalize(inputs), first)
        finalized, summary = first
        self.assertEqual(summary['candidates'], ['CCC'])
        self.assertEqual(summary['ranking_held'], ['AAA', 'BBB'])
        self.assertFalse(summary['ranking_complete'])
        self.assertEqual(summary['counts'], {'total': 3, 'selected': 1, 'excluded': 0, 'held': 2})
        for symbol in ('AAA', 'BBB'):
            result = finalized['stocks'][symbol]['result']
            self.assertEqual(result['status'], 'held')
            self.assertIsNone(result['plan'])
            self.assertEqual(result['reasons'], ['all_conditions_met', 'exact_turnover_ranking_unavailable'])
        self.assertEqual(finalized['stocks']['CCC'], original['stocks']['CCC'])

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
            self.assertEqual(record['inputs']['stocks']['MU']['inputs']['skipped'],
                             {'earnings': 'unverified_session', 'turnover': 'unverified_session'})
            self.assertTrue(any('/chart/MU?' in item['url'] for item in record['responses']))
            self.assertEqual(u.replay(out), record)

    def test_open_crossing_during_earnings_preserves_turnover_evidence_and_replays(self):
        source = UniverseResponses()
        current = [NOW]
        def fetch(url):
            body = source(url)
            if 'micron.com' in url:
                current[0] = NOW + timedelta(hours=2)
            return body
        record, _ = self.run_case(fetch, clock=lambda: current[0])
        row = record['inputs']['stocks']['MU']
        self.assertEqual(row['inputs']['skipped'], {})
        self.assertIn('turnover', row['inputs'])
        self.assertEqual(row['inputs']['collected_at'], current[0].isoformat())
        self.assertEqual(row['result']['status'], 'held')
        self.assertEqual(row['result']['reasons'], ['collection_outside_premarket'])
        self.assertIsNone(row['result']['plan'])

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
        self.assertEqual(record['result']['candidates'], [])
        self.assertEqual(record['inputs']['stocks']['MU']['result']['status'], 'held')
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
        self.assertEqual(record['result']['candidates'], [])
        self.assertIn('MU', record['inputs']['stocks'])
        self.assertEqual(record['inputs']['stocks']['MU']['result']['status'], 'held')

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
        source.sources['MU'].bars[-1]['tvol'] = '1500000'
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
