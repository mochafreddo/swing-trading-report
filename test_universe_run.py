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
