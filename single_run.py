"""Collect, evaluate and replay one MU development report using public data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from html.parser import HTMLParser
from functools import partial
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo


TOSS = 'https://openapi.tossinvest.com'
KIS = 'https://openapi.koreainvestment.com:9443'
NEWS = 'https://www.micron.com/about/press/news'
NY = ZoneInfo('America/New_York')
RULES = {
    'version': 1, 'symbol': 'MU', 'history_sessions': 50,
    'breakout_sessions': 20, 'volume_multiple': '1.5',
    'market_cap_min_usd': '10000000000', 'turnover_min_usd': '50000000',
    'atr_period': 14, 'earnings_sessions': 5,
    'entry_atr_multiple': '0.5', 'target_r_multiple': '2',
    'adjustment': 'raw_and_adjusted_must_match',
}


class DataError(ValueError):
    """A safe diagnostic code, containing no upstream response or credentials."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DataError('redirect_not_allowed')


def fetch_public(url: str, *, credentials: dict | None = None) -> str:
    """Use existing tokens only, in headers; never issue or persist a token."""
    host = urlparse(url).netloc
    credentials = os.environ if credentials is None else credentials
    headers = {'User-Agent': 'swing-trading-report/0.1', 'Accept': '*/*'}
    if host == urlparse(TOSS).netloc:
        required = ['TOSS_ACCESS_TOKEN']
    elif host == urlparse(KIS).netloc:
        required = ['KIS_ACCESS_TOKEN', 'KIS_APP_KEY', 'KIS_APP_SECRET']
    elif host in {'www.micron.com', 'investors.micron.com'}:
        required = []
    else:
        raise DataError('unexpected_source_host')
    if any(not credentials.get(key) for key in required):
        raise DataError('credentials_not_configured')
    if required:
        headers['Authorization'] = 'Bearer ' + credentials[required[0]]
        if len(required) > 1:
            headers.update(appkey=credentials['KIS_APP_KEY'],
                           appsecret=credentials['KIS_APP_SECRET'], tr_id='HHDFS76240000', custtype='P')
        # Toss MARKET_INFO permits three requests per second.
        time.sleep(0.35)
    try:
        with build_opener(NoRedirect).open(Request(url, headers=headers), timeout=20) as response:
            body = response.read(4_000_001)
            if len(body) > 4_000_000:
                raise DataError('response_too_large')
            return body.decode('utf-8')
    except HTTPError as error:
        error.close()
        raise DataError(f'http_{error.code}') from None
    except (URLError, TimeoutError, OSError, UnicodeError):
        raise DataError('network_or_encoding_error') from None


def credentials_for_run(path: Path | None, issue_tokens: bool) -> dict:
    names = {'TOSS_CLIENT_ID', 'TOSS_CLIENT_SECRET', 'TOSS_ACCESS_TOKEN',
             'KIS_APP_KEY', 'KIS_APP_SECRET', 'KIS_ACCESS_TOKEN'}
    credentials = {name: os.environ.get(name, '') for name in names}
    if path is not None:
        resolved = path.expanduser().resolve()
        metadata = resolved.stat()
        if (resolved.is_relative_to(Path(__file__).resolve().parent)
                or not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077
                or metadata.st_uid != os.getuid()):
            raise DataError('credentials_require_private_nonrepository_file')
        for line in resolved.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            key, separator, value = line.partition('=')
            key, value = key.strip(), value.strip()
            if not separator or key not in names:
                raise DataError('invalid_credentials_file')
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            credentials[key] = value
    if issue_tokens:
        requests = [
            ('TOSS_ACCESS_TOKEN', TOSS + '/oauth2/token', 'application/x-www-form-urlencoded',
             {'grant_type': 'client_credentials', 'client_id': credentials['TOSS_CLIENT_ID'],
              'client_secret': credentials['TOSS_CLIENT_SECRET']}),
            ('KIS_ACCESS_TOKEN', KIS + '/oauth2/tokenP', 'application/json',
             {'grant_type': 'client_credentials', 'appkey': credentials['KIS_APP_KEY'],
              'appsecret': credentials['KIS_APP_SECRET']}),
        ]
        if any(not all(payload.values()) for _, _, _, payload in requests):
            raise DataError('oauth_credentials_missing')
        for token_name, url, content_type, payload in requests:
            body = json.dumps(payload) if content_type == 'application/json' else urlencode(payload)
            try:
                request = Request(url, data=body.encode(), headers={'Content-Type': content_type})
                with build_opener(NoRedirect).open(request, timeout=20) as response:
                    token = json.loads(response.read(100_000))['access_token']
                if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
                    raise DataError('invalid_oauth_token')
                credentials[token_name] = token
            except (HTTPError, URLError, OSError, ValueError, KeyError, TypeError):
                raise DataError('oauth_failed_no_automatic_retry') from None
    return credentials


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise DataError('timezone_missing')
    return parsed


def number(value) -> Decimal:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise DataError('invalid_number')
    result = Decimal(value)
    if not result.is_finite() or result <= 0:
        raise DataError('nonpositive_or_nonfinite_number')
    return result


class NewsPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []
        self.articles: list[dict] = []
        self.in_article = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'a' and attributes.get('href', '').startswith(
                'https://investors.micron.com/news/press-release/'):
            self.links.append(attributes['href'])
        if tag == 'script' and attributes.get('type') == 'application/ld+json':
            self.in_article = True
            self.parts = []

    def handle_data(self, data):
        if self.in_article:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.in_article:
            self.in_article = False
            value = json.loads(''.join(self.parts))
            if isinstance(value, dict) and value.get('@type') == 'NewsArticle':
                self.articles.append(value)


def earnings(read: Callable[[str], str], report_day: date, as_of: datetime) -> dict:
    listing = NewsPage()
    listing.feed(read(NEWS))
    dates = []
    changes = []
    for url in sorted(set(listing.links)):
        page = NewsPage()
        page.feed(read(url))
        for article in page.articles:
            headline = article['headline']
            published = timestamp(article['datePublished'])
            if published > as_of:
                continue
            text = headline + ' ' + article.get('description', '')
            if (re.search(r'\b(earnings|quarterly|fiscal)\b', text, re.I)
                    and re.search(r'\b(cancelled|canceled|postponed|rescheduled)\b', text, re.I)):
                changes.append({'status': 'unconfirmed', 'source': url,
                                'published_at': published.isoformat(), 'reason': 'earnings_schedule_changed'})
            match = re.fullmatch(
                r'Micron Technology to Report Fiscal .+?Results(?: and Full Fiscal Year \d{4})? on ([A-Za-z]+ \d{1,2}, \d{4})',
                headline)
            if not match:
                continue
            event_day = datetime.strptime(match[1], '%B %d, %Y').date()
            if event_day < report_day:
                continue
            if re.search(r'\b(estimated|expected|tentative|cancelled|canceled|postponed|rescheduled)\b', text, re.I):
                return {'status': 'unconfirmed', 'source': url, 'reason': 'uncertain_earnings_announcement'}
            dates.append({'status': 'confirmed', 'date': event_day.isoformat(), 'source': url,
                          'published_at': published.isoformat(), 'title': headline,
                          'session': 'unknown'})
    if not dates:
        return {'status': 'unconfirmed', 'source': NEWS, 'reason': 'next_confirmed_earnings_not_found'}
    next_event = min(dates, key=lambda item: item['date'])
    newer_changes = [item for item in changes if timestamp(item['published_at']) >= timestamp(next_event['published_at'])]
    return max(newer_changes, key=lambda item: timestamp(item['published_at'])) if newer_changes else next_event


def calendar(read: Callable[[str], str], report_day: date, as_of: datetime) -> dict:
    def get(day):
        data = json.loads(read(TOSS + '/api/v1/market-calendar/US?' + urlencode({'date': str(day)})))['result']
        if date.fromisoformat(data['today']['date']) != day:
            raise DataError('calendar_date_mismatch')
        return data

    def trading_day(day):
        session = day['regularMarket']
        if not session:
            raise DataError('regular_session_missing')
        start, end = timestamp(session['startTime']), timestamp(session['endTime'])
        if not start < end or start.astimezone(NY).date().isoformat() != day['date']:
            raise DataError('invalid_session_time')
        return day['date']

    current = get(report_day)
    trading_day(current['today'])
    if not as_of.astimezone(NY).date() == report_day or not as_of < timestamp(current['today']['regularMarket']['startTime']):
        raise DataError('not_report_day_premarket')
    opening = current['today']['regularMarket']['startTime']
    past, future = [], [str(report_day)]
    for _ in range(50):
        previous = current['previousBusinessDay']
        day = trading_day(previous)
        if day >= current['today']['date'] or timestamp(previous['regularMarket']['endTime']) > as_of:
            raise DataError('invalid_previous_session')
        past.append(day)
        if len(past) < 50:
            current = get(date.fromisoformat(day))
    current = get(report_day)
    for _ in range(4):
        following = current['nextBusinessDay']
        day = trading_day(following)
        if day <= future[-1]:
            raise DataError('invalid_next_session')
        future.append(day)
        if len(future) < 5:
            current = get(date.fromisoformat(day))
    return {'past': list(reversed(past)), 'future': future, 'open': opening}


def collect(read: Callable[[str], str], report_day: date, as_of: datetime, synthetic: bool) -> dict:
    inputs: dict = {'issues': [], 'earnings': {'status': 'unconfirmed'}}
    def stage(name, work):
        try:
            inputs[name] = work()
        except DataError as error:
            inputs['issues'].append(name + ':' + str(error))
        except (KeyError, IndexError, TypeError, ValueError, InvalidOperation):
            inputs['issues'].append(name + ':invalid_response')

    def stock():
        listed = json.loads(read(TOSS + '/api/v1/stocks/all?' + urlencode(
            {'market': 'NASDAQ', 'status': 'ACTIVE', 'commonShare': 'true'})))['result']
        detail = json.loads(read(TOSS + '/api/v1/stocks?symbols=MU'))['result']
        matches = [row for row in detail if row['symbol'] == 'MU']
        if len(matches) != 1:
            raise DataError('stock_identity_mismatch')
        row = matches[0]
        return {key: row[key] for key in ['symbol', 'market', 'securityType', 'isCommonShare',
                                         'status', 'currency', 'sharesOutstanding']} | {
            'toss_available': any(item['symbol'] == 'MU' for item in listed)}

    stage('stock', stock)
    stage('calendar', lambda: calendar(read, report_day, as_of))
    previous = inputs.get('calendar', {}).get('past', [str(report_day - timedelta(days=1))])[-1]
    for adjusted in ('0', '1'):
        def bars(adjusted=adjusted):
            url = KIS + '/uapi/overseas-price/v1/quotations/dailyprice?' + urlencode(
                {'AUTH': '', 'EXCD': 'NAS', 'SYMB': 'MU', 'GUBN': '0',
                 'BYMD': previous.replace('-', ''), 'MODP': adjusted})
            data = json.loads(read(url))
            if data['rt_cd'] != '0':
                raise DataError('provider_rejected_request')
            if data['output1']['rsym'] != 'DNASMU':
                raise DataError('price_identity_mismatch')
            return data['output2']
        stage('bars_' + adjusted, bars)
    stage('earnings', lambda: earnings(read, report_day, as_of))
    if not synthetic:
        inputs['issues'].append('kis_regular_session_unverified')
    return inputs


def evaluate(inputs: dict) -> dict:
    held = list(inputs['issues'])
    result = {'status': 'held', 'reasons': held, 'metrics': {}, 'plan': None}
    if inputs['earnings'].get('status') != 'confirmed':
        held.append('next_confirmed_earnings_unavailable')
    if not all(key in inputs for key in ('stock', 'calendar', 'bars_0', 'bars_1')):
        return result
    try:
        stock = inputs['stock']
        shares = number(stock['sharesOutstanding'])
        if stock['currency'] != 'USD' or not isinstance(stock['isCommonShare'], bool):
            raise DataError('invalid_stock_contract')
        expected = inputs['calendar']['past']
        normalized = []
        for mode in ('0', '1'):
            raw = inputs['bars_' + mode]
            days = [datetime.strptime(row['xymd'], '%Y%m%d').date().isoformat() for row in raw]
            if len(days) != len(set(days)) or days != sorted(days, reverse=True):
                raise DataError('duplicate_or_unordered_bars')
            if days[:50] != list(reversed(expected)):
                raise DataError('missing_stale_or_future_bars')
            series = []
            for row in reversed(raw[:50]):
                values = {key: number(row[key]) for key in ('open', 'high', 'low', 'clos', 'tvol', 'tamt')}
                if not values['low'] <= min(values['open'], values['clos']) <= max(values['open'], values['clos']) <= values['high']:
                    raise DataError('invalid_ohlc')
                vwap = values['tamt'] / values['tvol']
                if not values['low'] <= vwap <= values['high']:
                    raise DataError('turnover_unit_or_session_mismatch')
                series.append(values)
            normalized.append(series)
        if normalized[0] != normalized[1]:
            raise DataError('corporate_action_adjustment_unverified')
        if held:
            return result
        series = normalized[1]
        last = series[-1]
        base = max(row['high'] for row in series[-21:-1])
        avg_volume = sum(row['tvol'] for row in series[-21:-1]) / 20
        turnover = sum(row['tamt'] for row in series[-20:]) / 20
        sma = sum(row['clos'] for row in series) / 50
        tr = [max(row['high'] - row['low'], abs(row['high'] - previous['clos']),
                  abs(row['low'] - previous['clos'])) for previous, row in zip(series, series[1:])]
        atr = sum(tr[:14]) / 14
        for value in tr[14:]:
            atr = (atr * 13 + value) / 14
        cap = shares * last['clos']
        metrics = {'market_cap_usd': cap, 'average_turnover_usd': turnover,
                   'breakout': base, 'volume_ratio': last['tvol'] / avg_volume, 'sma50': sma, 'atr14': atr}
        result['metrics'] = {key: str(value) for key, value in metrics.items()}
        checks = {
            'outside_stock_universe': stock['toss_available'] and stock['market'] in ('NASDAQ', 'NYSE')
            and stock['securityType'] in ('STOCK', 'FOREIGN_STOCK') and stock['isCommonShare'] and stock['status'] == 'ACTIVE',
            'market_cap_below_minimum': cap >= Decimal(RULES['market_cap_min_usd']),
            'turnover_below_minimum': turnover >= Decimal(RULES['turnover_min_usd']),
            'close_not_above_breakout': last['clos'] > base,
            'volume_below_multiple': last['tvol'] >= avg_volume * Decimal(RULES['volume_multiple']),
            'close_not_above_sma50': last['clos'] > sma,
        }
        event = date.fromisoformat(inputs['earnings']['date'])
        if event < date.fromisoformat(inputs['calendar']['future'][0]):
            raise DataError('earnings_date_is_past')
        checks['earnings_within_exclusion_window'] = event > date.fromisoformat(inputs['calendar']['future'][-1])
        excluded = [reason for reason, passed in checks.items() if not passed]
        if excluded:
            return result | {'status': 'excluded', 'reasons': excluded}
        entry = last['clos']
        stop = base - atr
        risk = entry - stop
        if min(atr, stop, risk) <= 0:
            raise DataError('invalid_price_plan')
        plan = {'entry_low': entry, 'entry_high': entry + atr * Decimal('0.5'),
                'stop': stop, 'risk': risk, 'target': entry + risk * 2}
        return result | {'status': 'selected', 'reasons': ['all_conditions_met'],
                         'plan': {key: str(value) for key, value in plan.items()}}
    except DataError as error:
        held.append(str(error))
    except (KeyError, ValueError, TypeError, InvalidOperation):
        held.append('invalid_required_data')
    return result | {'metrics': {}}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def render(record: dict) -> str:
    result = record['result']
    inputs = record['inputs']
    labels = {'selected': '매수 후보 선정', 'excluded': '조건 충족 후보 없음', 'held': '평가 불가·보류'}
    lines = ['# MU 한 종목 개발 검증 보고서', '',
             f"자료 구분: {'검증용 사례' if record['synthetic'] else '실제 자동 수집 자료'}.", '',
             f"보고일: {record['report_date']} (미국 동부시간). 확인 시각: {record['as_of']}.", '',
             f"판정: {labels[result['status']]}. 사유: {', '.join(result['reasons'])}.", '',
             '탐색 대상은 MU 한 종목이다. 전체 종목군·후보 순위 비교는 미검증이며 첫 마일스톤 완료가 아니다.', '',
             'AI 설명: 미연결. 텔레그램 전송: 미연결. 뉴스 위험 요약·이전 후보 경과: 후속 범위.', '']
    cal = inputs.get('calendar', {})
    if cal:
        lines += [f"일봉 구간: {cal['past'][0]}~{cal['past'][-1]} (50거래일). 실적 제외 구간: {cal['future'][0]}~{cal['future'][-1]}.", '']
    event = inputs['earnings']
    lines += [f"다음 확정 실적 발표일: {event.get('date', '확인 불가')} ({event.get('status')}).", '']
    if event.get('source'):
        checked = next((item['checked_at'] for item in record['responses'] if item['url'] == event['source']), '확인 불가')
        lines += [f"[실적 일정 출처]({event['source']}). 확인 시각: {checked}. 공지 발행 시각: {event.get('published_at', '확인 불가')}.", '']
    if result['metrics']:
        lines += ['| 계산 항목 | 값 |', '| --- | --- |']
        lines += [f'| {key} | {value} |' for key, value in result['metrics'].items()]
        lines += ['', '시가총액은 조회 시점 발행주식수 × 전일 종가(USD) 계산값이다. 거래대금은 제공자의 일별 금액을 사용한다.', '']
    if result['plan']:
        plan = {key: f'{Decimal(value):.2f}' for key, value in result['plan'].items()}
        lines += [f"진입 검토 구간: {plan['entry_low']}~{plan['entry_high']} USD (전일 종가~전일 종가 + 0.5ATR). 구간 밖에서는 진입을 보류한다.", '',
                  f"손실 제한 기준: {plan['stop']} USD = 돌파 기준선 − ATR.", '',
                  f"예시 1R: {plan['risk']} USD = 전일 종가 − 손실 제한 기준.", '',
                  f"예시 이익 실현 기준: {plan['target']} USD = 전일 종가 + 2R.", '',
                  '진입 계획은 보고일 정규장 하루에만 유효하다. 실제 진입가가 다르면 1R과 이익 실현 기준을 다시 계산한다. 실제 체결과 최대 손실을 보장하지 않는다.', '']
    else:
        lines += ['선정된 매수 후보가 없어 진입·손실 제한·이익 실현 가격 계획을 제시하지 않는다.', '']
    lines += ['수집 근거와 요청별 확인 시각:', '']
    lines += [f"- [{item['url']}]({item['url']}) — {item['checked_at']}: {item.get('error', '수집됨')}" for item in record['responses']]
    return '\n'.join(lines) + '\n'


def run(output: Path, report_day: date, *, fetch: Callable[[str], str] = fetch_public,
        now: datetime | None = None, synthetic: bool = False) -> dict:
    as_of = now or datetime.now(timezone.utc)
    timestamp(as_of.isoformat())
    output.mkdir(parents=True, exist_ok=False)
    responses = []
    def read(url):
        item = {'url': url}
        try:
            item['body'] = fetch(url)
        except DataError as error:
            item['error'] = str(error)
            raise
        finally:
            item['checked_at'] = (now or datetime.now(timezone.utc)).isoformat()
            responses.append(item)
        return item['body']
    with localcontext() as context:
        context.prec = 28
        inputs = collect(read, report_day, as_of, synthetic)
        result = evaluate(inputs)
    record = {'format_version': 1, 'rules': RULES, 'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'contract': Path(__file__).with_name('docs').joinpath('single-run-contract.md').read_text(),
              'report_date': str(report_day), 'as_of': as_of.isoformat(), 'synthetic': synthetic,
              'responses': responses, 'inputs': inputs, 'result': result}
    record['sha256'] = digest(record)
    (output / 'record.json').write_text(json.dumps(record, indent=2, ensure_ascii=False) + '\n')
    (output / 'report.md').write_text(render(record))
    return record


def replay(output: Path) -> dict:
    record = json.loads((output / 'record.json').read_text())
    checksum = record.pop('sha256')
    if digest(record) != checksum:
        raise DataError('record_integrity_mismatch')
    if (record['code_sha256'] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            or record['rules'] != RULES or record['format_version'] != 1):
        raise DataError('replay_version_mismatch')
    remaining = iter(record['responses'])
    def read(url):
        item = next(remaining)
        if item['url'] != url:
            raise DataError('replay_request_mismatch')
        if 'error' in item:
            raise DataError(item['error'])
        return item['body']
    with localcontext() as context:
        context.prec = 28
        inputs = collect(read, date.fromisoformat(record['report_date']), timestamp(record['as_of']), record['synthetic'])
        result = evaluate(inputs)
    if next(remaining, None) is not None or inputs != record['inputs'] or result != record['result']:
        raise DataError('replay_result_mismatch')
    if (output / 'report.md').read_text() != render(record):
        raise DataError('replay_report_mismatch')
    record['sha256'] = checksum
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    live = sub.add_parser('run')
    live.add_argument('--output', type=Path, required=True)
    live.add_argument('--report-date', type=date.fromisoformat)
    live.add_argument('--credentials-file', type=Path, help='Private file outside the repository (mode 600).')
    live.add_argument('--issue-tokens', action='store_true',
                      help='Issue tokens in memory. Invalidates the previous Toss token; KIS may send an alert.')
    saved = sub.add_parser('replay')
    saved.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'replay':
            record = replay(args.output)
        else:
            if args.output.exists():
                raise DataError('output_already_exists')
            credentials = credentials_for_run(args.credentials_file, args.issue_tokens)
            record = run(args.output, args.report_date or datetime.now(NY).date(),
                         fetch=partial(fetch_public, credentials=credentials))
        print(json.dumps({'status': record['result']['status'], 'reasons': record['result']['reasons'],
                          'output': str(args.output)}, ensure_ascii=False))
        return 0 if args.command == 'replay' or record['result']['status'] != 'held' else 2
    except DataError as error:
        print('실행 또는 재현 실패: ' + str(error))
        return 1
    except (OSError, ValueError, KeyError, StopIteration):
        print('실행 또는 재현 실패. 입력·버전·기존 출력 경로를 확인하세요.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
