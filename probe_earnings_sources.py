#!/usr/bin/env python3
"""Public IR research and runtime collector verification; no credentials.

Run: python3 probe_earnings_sources.py --output runs/issue233-ir-probe-20260915
Replay: python3 probe_earnings_sources.py --replay runs/issue233-ir-probe-20260915
Checks: python3 probe_earnings_sources.py --self-check
"""

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

import single_run as s


# These are source locations, not earnings dates or preselected article URLs.
SOURCES = [
    ('MU', 'Micron', 'https://www.micron.com/about/press/news', ('micron.com',)),
    ('NVDA', 'NVIDIA', 'https://nvidianews.nvidia.com/news', ('nvidia.com',)),
    ('AAPL', 'Apple', 'https://www.apple.com/newsroom/archive/', ('apple.com',)),
    ('MSFT', 'Microsoft', 'https://www.microsoft.com/en-us/investor/events/default', ('microsoft.com',)),
    ('AMZN', 'Amazon', 'https://ir.aboutamazon.com/news-release/default.aspx', ('aboutamazon.com',)),
    ('GOOGL', 'Alphabet', 'https://abc.xyz/investor/news/default.aspx', ('abc.xyz',)),
    ('META', 'Meta', 'https://investor.atmeta.com/investor-news/default.aspx', ('atmeta.com',)),
    ('JPM', 'JPMorgan', 'https://www.jpmorganchase.com/ir/news', ('jpmorganchase.com',)),
    ('XOM', 'ExxonMobil', 'https://corporate.exxonmobil.com/news/news-releases', ('exxonmobil.com',)),
    ('COST', 'Costco', 'https://investor.costco.com/news/default.aspx', ('costco.com',)),
    ('NKE', 'NIKE', 'https://investors.nike.com/investors/news-events-and-reports/', ('nike.com',)),
]
MONTHS = {name.lower(): index for index, name in enumerate(
    ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
     'September', 'October', 'November', 'December'), 1)}
DATE = re.compile(r'\b(' + '|'.join(MONTHS) + r')\s+(\d{1,2}),?\s+(20\d{2})\b', re.I)
EARNINGS = re.compile(r'\b(earnings|financial results|quarter.{0,25}results|fiscal.{0,30}results)\b', re.I)
ANNOUNCEMENT = re.compile(r'\b(to (?:report|release|announce)|will (?:report|release|announce|hold|host)|sets? (?:a )?conference call|schedules?)\b', re.I)
UNCERTAIN = re.compile(r'\b(estimated|expected|tentative|cancelled|canceled|postponed|rescheduled|delay(?:ed)?)\b', re.I)


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.anchor = None
        self.skip = 0
        self.json_text = None
        self.structured = []
        self.metadata = {}
        self.parts = []
        self.title_parts = []
        self.heading_parts = []
        self.in_title = False
        self.in_h1 = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('type', '').lower() == 'application/ld+json':
            self.json_text = []
        if tag in ('script', 'style'):
            self.skip += 1
        if tag == 'meta':
            self.metadata[attrs.get('property', attrs.get('name', ''))] = attrs.get('content', '')
        if tag == 'a':
            self.anchor = [attrs.get('href', ''), []]
        if tag == 'title':
            self.in_title = True
        if tag == 'h1':
            self.in_h1 = True
        if tag in ('p', 'div', 'br', 'li', 'h1', 'h2'):
            self.parts.append('\n')

    def handle_data(self, value):
        if self.json_text is not None:
            self.json_text.append(value)
        if self.skip:
            return
        self.parts.append(value)
        if self.anchor:
            self.anchor[1].append(value)
        if self.in_title:
            self.title_parts.append(value)
        if self.in_h1:
            self.heading_parts.append(value)

    def handle_endtag(self, tag):
        if tag == 'script' and self.json_text is not None:
            try:
                self.structured.append(json.loads(''.join(self.json_text)))
            except (ValueError, TypeError):
                pass
            self.json_text = None
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        if tag == 'a' and self.anchor:
            self.links.append((self.anchor[0], ' '.join(self.anchor[1])))
            self.anchor = None
        if tag == 'title':
            self.in_title = False
        if tag == 'h1':
            self.in_h1 = False
        if tag in ('p', 'div', 'li', 'h1', 'h2'):
            self.parts.append('\n')


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def article(page):
    for blob in page.structured:
        for item in objects(blob):
            if item.get('@type') in ('NewsArticle', 'Article', 'BlogPosting'):
                return (str(item.get('headline', '')), str(item.get('datePublished', '')),
                        str(item.get('description', '')) + '\n' + str(item.get('articleBody', '')))
    title = page.metadata.get('og:title') or ''.join(page.heading_parts) or ''.join(page.title_parts)
    published = (page.metadata.get('article:published_time') or page.metadata.get('date')
                 or page.metadata.get('published_time') or page.metadata.get('pubdate')
                 or page.metadata.get('publishdate') or '')
    return title, published, page.metadata.get('description', '')


def classify(title, published, text, as_of):
    """Conservative schedule candidate extraction, shared by live and controls."""
    result = {'title': title, 'published_at': published or None, 'status': 'unconfirmed'}
    if not EARNINGS.search(title) or not ANNOUNCEMENT.search(title):
        if (EARNINGS.search(title) and re.search(r'\b(?:announces|reports)\b', title, re.I)
                and re.fullmatch(r'20\d{2}-\d{2}-\d{2}', published)):
            try:
                if date.fromisoformat(published) < as_of.astimezone(ZoneInfo('America/New_York')).date():
                    return dict(result, status='past_results_article', reason='dated_results_article_not_future_schedule')
            except ValueError:
                pass
        return dict(result, reason='not_a_supported_earnings_advance_announcement')
    if UNCERTAIN.search(title):
        return dict(result, reason='uncertain_or_changed_schedule')
    try:
        published_at = datetime.fromisoformat(published.replace('Z', '+00:00'))
        if published_at.tzinfo is None:
            # Date-only publication does not establish intraday availability.
            if published_at.date() >= as_of.astimezone(ZoneInfo('America/New_York')).date():
                return dict(result, reason='publication_time_not_verified')
            published_at = published_at.replace(tzinfo=timezone.utc)
        if published_at > as_of:
            return dict(result, reason='publication_after_asof')
    except (TypeError, ValueError):
        return dict(result, reason='publication_time_not_verified')
    chunks = [title] + re.split(r'\n+|(?<=[.!?])\s+', text)
    relevant = [chunk for chunk in chunks if EARNINGS.search(chunk) and ANNOUNCEMENT.search(chunk)]
    if any(UNCERTAIN.search(chunk) for chunk in relevant):
        return dict(result, reason='uncertain_or_changed_schedule')
    dates = []
    for chunk in relevant:
        for match in DATE.finditer(re.split(r'\bwhich ended\b', chunk, flags=re.I)[0]):
            try:
                event_day = date(int(match[3]), MONTHS[match[1].lower()], int(match[2]))
            except ValueError:
                continue
            dates.append((event_day, ' '.join(chunk.split())[:650]))
    unique = {item[0] for item in dates}
    if not unique:
        return dict(result, reason='no_explicit_year_schedule_in_announcement')
    if len(unique) != 1:
        return dict(result, reason='multiple_dates_need_review', candidate_dates=sorted(map(str, unique)))
    event_day, evidence = dates[0]
    return dict(result, status='past_announcement' if event_day < as_of.astimezone(ZoneInfo('America/New_York')).date() else 'confirmed_candidate',
                date=str(event_day), evidence=evidence,
                reason='company_advance_announcement_candidate_not_complete_next_event_proof')


def check():
    as_of = datetime(2026, 9, 15, tzinfo=timezone.utc)
    title = 'Example to Report Fiscal Fourth Quarter Results on September 30, 2026'
    published = '2026-09-01T12:00:00Z'
    assert classify(title, published, '', as_of)['status'] == 'confirmed_candidate'
    cases = {
        'expected_title': ('Expected ' + title, published, ''),
        'postponed_title': (title + ' postponed', published, ''),
        'expected_body': (title, published, 'Example is expected to report earnings on September 30, 2026.'),
        'rescheduled_body': (title, published, 'Example will report earnings on September 30, 2026, rescheduled.'),
        'general_event': ('Example to Host Technology Conference on September 30, 2026', published, ''),
        'future_publication': (title, '2026-09-20T12:00:00Z', ''),
        'missing_publication': (title, '', ''),
        'date_only_current_new_york_day': (title, '2026-09-14', ''),
        'conflicting_dates': (title, published, 'Example will report earnings on October 1, 2026.'),
    }
    for name, args in cases.items():
        assert classify(*args, as_of)['status'] == 'unconfirmed', name
    assert classify(title.replace('September 30', 'August 30'), published, '', as_of)['status'] == 'past_announcement'
    assert classify(title.replace('September 30', 'September 14'), published, '', as_of)['status'] == 'confirmed_candidate'
    assert classify('Example Announces Financial Results', '2026-07-31', '', as_of)['status'] == 'past_results_article'
    # Demonstrate the guard catches the intended defect under the same procedure.
    global UNCERTAIN
    original = UNCERTAIN
    UNCERTAIN = re.compile(r'(?!)')
    try:
        assert classify('Expected ' + title, published, '', as_of)['status'] == 'unconfirmed'
    except AssertionError:
        failed_without_guard = True
    else:
        failed_without_guard = False
    finally:
        UNCERTAIN = original
    assert failed_without_guard, 'negative control did not expose missing uncertainty guard'
    return {'positive': 1, 'rejection_cases': len(cases), 'past_cases': 2, 'new_york_day_boundary': 1,
            'uncertainty_guard_removed_assertion_failed': failed_without_guard}


def allowed(url, hosts):
    parsed = urlsplit(url)
    return parsed.scheme == 'https' and not parsed.username and not parsed.password and any(
        parsed.hostname == host or (parsed.hostname or '').endswith('.' + host) for host in hosts)


class Redirects(HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl, self.hosts):
            raise URLError('redirect_outside_source_hosts')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def probe(read, as_of, max_articles):
    results = []
    for symbol, company, listing_url, hosts in SOURCES:
        result = {'symbol': symbol, 'company': company, 'listing_url': listing_url,
                  'status': 'unconfirmed', 'articles': []}
        results.append(result)
        listing = read(listing_url, hosts)
        if listing is None:
            result['reason'] = 'listing_fetch_failed'
            continue
        page = Page()
        page.feed(listing)
        result['listing_pages'] = [listing_url]
        listing_pages = [(listing_url, page)]
        next_links = [(urljoin(listing_url, href), label) for href, label in page.links
                      if label.strip().lower() == 'next' and allowed(urljoin(listing_url, href), hosts)]
        if next_links:
            next_url = next_links[0][0]
            next_body = read(next_url, hosts)
            result['listing_pages'].append(next_url)
            if next_body is not None:
                next_page = Page()
                next_page.feed(next_body)
                listing_pages.append((next_url, next_page))
        links = []
        discovery = {}
        for source_url, source_page in listing_pages:
            for href, label in source_page.links:
                url = urljoin(source_url, href)
                if (allowed(url, hosts) and url != listing_url and not urlsplit(url).fragment
                        and EARNINGS.search(label + ' ' + href.replace('-', ' ')) and url not in discovery):
                    links.append((url, ' '.join(label.split())))
                    discovery[url] = source_url
        links.sort(key=lambda x: (not bool(ANNOUNCEMENT.search(x[1] + ' ' + x[0].replace('-', ' '))), x[0]))
        result.update(listing_access=True, discovered_links=len(links),
                      selected_links=[{'url': url, 'label': label} for url, label in links[:max_articles]],
                      discovery_truncated=len(links) > max_articles)
        for url, label in links[:max_articles]:
            body = read(url, hosts)
            if body is None:
                result['articles'].append({'url': url, 'status': 'unconfirmed', 'reason': 'article_fetch_failed'})
                continue
            parsed = Page()
            parsed.feed(body)
            title, published, structured_text = article(parsed)
            judgement = classify(title, published, structured_text + '\n' + ''.join(parsed.parts), as_of)
            result['articles'].append(dict(judgement, url=url, discovered_from=discovery[url], link_label=label))
        candidates = [item for item in result['articles'] if item['status'] == 'confirmed_candidate']
        result['status'] = 'confirmed_candidate_found' if candidates else 'unconfirmed'
        result['reason'] = 'bounded_source_scan_not_proof_of_next_event' if candidates else (
            'no_matching_static_links' if not links else 'no_verified_future_candidate_in_bounded_scan')
        result['candidate_dates'] = sorted(set(item['date'] for item in candidates))
        print(f'{symbol}: {result["reason"]}; links={len(links)}', flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--self-check', action='store_true')
    mode.add_argument('--output', type=Path)
    mode.add_argument('--replay', type=Path)
    parser.add_argument('--max-articles', type=int, default=4, choices=range(1, 11))
    parser.add_argument('--production', action='store_true', help='Exercise the runtime IR collector on registered issuers')
    args = parser.parse_args()
    controls = check()
    if args.self_check:
        print(json.dumps(controls, indent=2))
        return
    if args.replay:
        record = json.loads((args.replay / 'record.json').read_text())
        assert record['code_sha256'] == sha256(Path(__file__).read_bytes()).hexdigest(), 'code changed'
        iterator = iter(record['requests'])
        def read(url, hosts):
            entry = next(iterator)
            assert entry['url'] == url
            if record.get('production') and entry['status'] != 200:
                raise s.DataError(str(entry['status']))
            if not entry.get('body_file'):
                return None
            raw = (args.replay / entry['body_file']).read_bytes()
            assert sha256(raw).hexdigest() == entry['sha256']
            return raw.decode('utf-8', errors='replace') if entry['status'] == 200 else None
        if record.get('production'):
            import universe_run as u
            assert record['runtime_sha256'] == u.code_hash(), 'runtime changed'
        results = (production_probe if record.get('production') else probe)(
            read, datetime.fromisoformat(record['as_of']), record['max_articles'])
        assert next(iterator, None) is None
        assert results == record['results'], 'replay differs'
        print('Replay matched without network.')
        return
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'responses').mkdir()
    (args.output / 'probe_source.py').write_bytes(Path(__file__).read_bytes())
    record = {'as_of': datetime.now(timezone.utc).isoformat(), 'sources': SOURCES,
              'max_articles': args.max_articles, 'controls': controls, 'requests': [],
              'code_sha256': sha256(Path(__file__).read_bytes()).hexdigest()}
    if args.production:
        import universe_run as u
        record.update(production=True, runtime_sha256=u.code_hash())
    started = time.monotonic()
    def read(url, hosts):
        assert allowed(url, hosts)
        time.sleep(0.3)
        entry = {'url': url, 'fetched_at': datetime.now(timezone.utc).isoformat()}
        record['requests'].append(entry)
        request_started = time.monotonic()
        raw = None
        try:
            if args.production:
                raw = s.fetch_public(url, credentials={}, public_hosts=hosts).encode()
                entry.update(status=200, final_url=url)
            else:
                req = Request(url, headers={'User-Agent': 'PublicIRSourceProbe/1.0', 'Accept': 'text/html'})
                with build_opener(Redirects(hosts)).open(req, timeout=20) as response:
                    entry.update(status=response.status, final_url=response.url,
                                 content_type=response.headers.get('Content-Type'))
                    raw = response.read(5_000_001)
                    if len(raw) > 5_000_000:
                        entry.update(status='oversized_response', reason='body_over_5MB')
                        raw = None
        except s.DataError as error:
            entry.update(status=str(error), reason='runtime_fetch_failed')
        except HTTPError as error:
            entry.update(status=error.code, reason='http_error')
            raw = error.read(100_000)
        except (URLError, TimeoutError, OSError) as error:
            entry.update(status='transport_error', reason=type(error).__name__)
        entry['elapsed_seconds'] = round(time.monotonic() - request_started, 3)
        if raw is not None:
            path = f'responses/{len(record["requests"]):03d}.html'
            (args.output / path).write_bytes(raw)
            entry.update(body_file=path, bytes=len(raw), sha256=sha256(raw).hexdigest())
        if args.production and entry['status'] != 200:
            raise s.DataError(str(entry['status']))
        return raw.decode('utf-8', errors='replace') if raw is not None and entry['status'] == 200 else None
    record['results'] = (production_probe if args.production else probe)(
        read, datetime.fromisoformat(record['as_of']), args.max_articles)
    record.update(request_count=len(record['requests']), elapsed_seconds=round(time.monotonic() - started, 3))
    (args.output / 'record.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(f'Saved {args.output}/record.json; requests={record["request_count"]}; seconds={record["elapsed_seconds"]}')


def production_probe(read, as_of, max_articles):
    import universe_run as u
    results = []
    for symbol, company, listing_url, hosts in SOURCES:
        source = u.DEFAULT_EARNINGS_SOURCES[symbol]
        allowed_hosts = tuple({urlsplit(source[key]).hostname for key in ('listing_url', 'article_prefix')})
        def required_read(url):
            body = read(url, allowed_hosts)
            if body is None:
                raise s.DataError('source_fetch_failed')
            return body
        try:
            event = s.earnings(required_read, as_of.astimezone(s.NY).date(), as_of, source)
        except (s.DataError, ValueError, KeyError, TypeError):
            event = {'status': 'unconfirmed', 'collection_status': 'failed', 'reason': 'source_fetch_or_parse_failed'}
        results.append({'symbol': symbol, 'event': event})
        print(f'{symbol}: {event["status"]}; {event.get("reason", event.get("date"))}', flush=True)
    return results


if __name__ == '__main__':
    main()
