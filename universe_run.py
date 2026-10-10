"""Collect the full Toss NYSE/Nasdaq universe and replay a local report."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from functools import partial
from pathlib import Path
from urllib.parse import urlencode, urlparse

import earnings as ir
import execution_record as records
import single_run as s

RULES = {
    "version": 6,
    "calculation": {key: value for key, value in s.RULES.items() if key != "symbol"},
    "markets": ["NASDAQ", "NYSE"],
    "types": ["STOCK", "FOREIGN_STOCK"],
    "maximum_candidates": 3,
    "order": ["volume_ratio_desc", "exact_average_turnover_desc", "symbol_asc"],
    "unverified_turnover_ties": "held",
}
CONTRACT = Path(__file__).with_name("docs") / "universe-run-contract.md"
# Reviewed issuer/depositary terms, bound to the security rather than the ticker alone.
REVIEWED_NON_COMMON = {
    "CORZZ": {
        "market": "NASDAQ",
        "isin": "US21874A1300",
        "english_name": "CORE SCIENTIFIC INC C/WTS 23/01/2029 (TO PUR COM)",
        "reviewed_on": "2026-09-27",
        "classification": "warrant",
        "source": "https://investors.corescientific.com/news-events/press-releases/detail/81/core-scientific-announces-tranche-2-warrants-triggering-event",
        "required_text": ["Tranche 2 warrants (CORZZ, CUSIP 21874A130)"],
    },
    "PSNYW": {
        "market": "NASDAQ",
        "isin": "US7311056078",
        "english_name": "POLESTAR AUTOMOTIVE HOLDING UK PLC SPON ADS C-1 EACH RP 30 C",
        "reviewed_on": "2026-09-28",
        "classification": "class_c1_ads_subscription_right",
        "source": "https://depositaryreceipts.citi.com/adr/common/file.aspx?idf=7428",
        "required_body_sha256": "775abe2adbdeb6d944b82823842d7fdeda56275fcb8a099472bbad63e82ee0f6",
    },
}
DEFAULT_EARNINGS_SOURCES = {
    "MU": {
        "listing_url": s.NEWS,
        "article_prefix": "https://investors.micron.com/news/press-release/",
        "company": "Micron Technology",
    }
}
DEFAULT_EARNINGS_SOURCES.update(
    {
        symbol: {"company": company, "listing_url": listing, "article_prefix": prefix}
        for symbol, company, listing, prefix in [
            (
                "NVDA",
                "NVIDIA",
                "https://nvidianews.nvidia.com/news",
                "https://nvidianews.nvidia.com/news/",
            ),
            (
                "AAPL",
                "Apple",
                "https://www.apple.com/newsroom/archive/",
                "https://www.apple.com/newsroom/",
            ),
            (
                "MSFT",
                "Microsoft",
                "https://www.microsoft.com/en-us/investor/events/default",
                "https://news.microsoft.com/",
            ),
            (
                "AMZN",
                "Amazon.com",
                "https://ir.aboutamazon.com/news-release/default.aspx",
                "https://ir.aboutamazon.com/news-release/news-release-details/",
            ),
            (
                "GOOGL",
                "Alphabet",
                "https://abc.xyz/investor/news/default.aspx",
                "https://abc.xyz/investor/news/news-details/",
            ),
            (
                "GOOG",
                "Alphabet",
                "https://abc.xyz/investor/news/default.aspx",
                "https://abc.xyz/investor/news/news-details/",
            ),
            (
                "META",
                "Meta",
                "https://investor.atmeta.com/investor-news/default.aspx",
                "https://investor.atmeta.com/investor-news/press-release-details/",
            ),
            (
                "JPM",
                "JPMorgan",
                "https://www.jpmorganchase.com/ir/news",
                "https://www.jpmorganchase.com/ir/news/",
            ),
            (
                "XOM",
                "ExxonMobil",
                "https://corporate.exxonmobil.com/news/news-releases",
                "https://corporate.exxonmobil.com/news/news-releases/",
            ),
            (
                "COST",
                "Costco Wholesale Corporation",
                "https://investor.costco.com/news/default.aspx",
                "https://investor.costco.com/news/news-details/",
            ),
            (
                "NKE",
                "NIKE, Inc.",
                "https://investors.nike.com/investors/news-events-and-reports/",
                "https://investors.nike.com/investors/news-events-and-reports/investor-news/investor-news-details/",
            ),
            (
                "RGEN",
                "Repligen",
                "https://investors.repligen.com/press-releases/default.aspx",
                "https://investors.repligen.com/press-releases/news-details/",
            ),
        ]
    }
)


def checked_sources(sources):
    result = DEFAULT_EARNINGS_SOURCES | (sources or {})
    for symbol, source in result.items():
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,19}", symbol)
            or set(source) != {"company", "listing_url", "article_prefix"}
            or not isinstance(source["company"], str)
            or not source["company"].strip()
        ):
            raise s.DataError("invalid_earnings_source")
        for key in ("listing_url", "article_prefix"):
            url = urlparse(source[key])
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.port not in (None, 443)
                or url.hostname in {urlparse(s.TOSS).hostname, urlparse(s.KIS).hostname}
            ):
                raise s.DataError("invalid_earnings_source_url")
        if not source["article_prefix"].endswith("/"):
            raise s.DataError("earnings_article_prefix_requires_path_boundary")
    return result


def attempt(issues, name, work):
    try:
        return work()
    except s.DataError as error:
        issues.append(name + ":" + str(error))
    except KeyError, IndexError, TypeError, ValueError, InvalidOperation:
        issues.append(name + ":invalid_response")
    return None


def discover(read):
    universe = {"issues": [], "markets": {}, "symbols": {}}
    for market in RULES["markets"]:
        issues = []
        lists = {}
        for kind in ["", *RULES["types"]]:
            query = {"market": market, "status": "ACTIVE", "commonShare": "true"}
            if kind:
                query["securityType"] = kind

            def listing(*, kind=kind, query=query):
                data = json.loads(
                    read(s.TOSS + "/api/v1/stocks/all?" + urlencode(query))
                )
                if set(data) != {"result"} or not isinstance(data["result"], list):
                    raise s.DataError("unexpected_list_envelope")
                rows = {}
                for row in data["result"]:
                    symbol = row["symbol"]
                    if (
                        not isinstance(symbol, str)
                        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,19}", symbol)
                        or symbol in rows
                        or row["isCommonShare"] is not True
                        or not isinstance(row["securityType"], str)
                        or (kind and row["securityType"] != kind)
                    ):
                        raise s.DataError("invalid_or_duplicate_listing")
                    rows[symbol] = row
                return rows

            result = attempt(issues, kind or "all", listing)
            lists[kind] = result or {}
        filtered = {
            symbol: row
            for symbol, row in lists[""].items()
            if row["securityType"] in RULES["types"]
        }
        partitioned = {
            symbol: row
            for kind in RULES["types"]
            for symbol, row in lists[kind].items()
        }
        if not lists[""] or filtered != partitioned:
            issues.append("list_coverage_mismatch")
        union = filtered | partitioned
        conflicts = {}
        for symbol in sorted(union):
            general = lists[""].get(symbol)
            typed = [
                lists[kind][symbol] for kind in RULES["types"] if symbol in lists[kind]
            ]
            if general != partitioned.get(symbol) or len(typed) > 1:
                conflicts[symbol] = {
                    "general": general,
                    "typed": typed,
                    "reason": "typed_only"
                    if general is None
                    else "general_only"
                    if not typed
                    else "row_conflict",
                }
        universe["markets"][market] = {
            "returned": {kind or "all": len(rows) for kind, rows in lists.items()},
            "symbols": sorted(union),
            "issues": issues,
            "conflicts": conflicts,
        }
        universe["issues"].extend(market + ":" + issue for issue in issues)
        for symbol, row in union.items():
            if symbol in universe["symbols"]:
                universe["issues"].append("duplicate_symbol_across_markets:" + symbol)
                universe["symbols"][symbol]["ambiguous"] = True
            else:
                universe["symbols"][symbol] = {"market": market, "listing": row}
    return universe


def classify_non_common(read, universe, item, row, symbol, as_of, checked_at):
    """Verify reviewed security identity and its source before excluding it."""
    evidence = REVIEWED_NON_COMMON[symbol]
    conflict = universe["markets"][item["market"]]["conflicts"].get(symbol)
    listing_rows = [item["listing"]]
    if conflict:
        listing_rows += (
            [conflict["general"]] if conflict["general"] else []
        ) + conflict["typed"]
    if (
        item.get("ambiguous")
        or item["market"] != evidence["market"]
        or row.get("market") != evidence["market"]
        or row.get("symbol") != symbol
        or row.get("isinCode") != evidence["isin"]
        or row.get("englishName") != evidence["english_name"]
        or row.get("status") != "ACTIVE"
        or row.get("currency") != "USD"
        or any(
            entry.get("symbol") != symbol or entry.get("isinCode") != evidence["isin"]
            for entry in listing_rows
        )
    ):
        raise s.DataError("security_classification_identity_mismatch")
    if date.fromisoformat(evidence["reviewed_on"]) > as_of.astimezone(s.NY).date():
        raise s.DataError("security_classification_review_in_future")
    body = read(evidence["source"])
    body_sha256 = hashlib.sha256(body.encode()).hexdigest()
    if "required_body_sha256" in evidence:
        if body_sha256 != evidence["required_body_sha256"]:
            raise s.DataError("security_classification_evidence_missing")
    else:
        page = ir.NewsPage()
        page.feed(body)
        text = " ".join("".join(page.text).split())
        if not all(fragment in text for fragment in evidence["required_text"]):
            raise s.DataError("security_classification_evidence_missing")
    return evidence | {
        "body_sha256": body_sha256,
        "checked_at": checked_at(),
    }


def collect(read, report_day, as_of, earnings_sources, checked_at):
    universe = discover(read)
    inputs = {"universe": universe, "issues": [], "stocks": {}}
    cal = attempt(
        inputs["issues"], "calendar", lambda: s.calendar(read, report_day, as_of)
    )
    inputs["calendar"] = cal
    symbols = sorted(universe["symbols"])
    for start in range(0, len(symbols), 200):
        batch = symbols[start : start + 200]
        issues = []

        def details(*, batch=batch):
            data = json.loads(
                read(
                    s.TOSS + "/api/v1/stocks?" + urlencode({"symbols": ",".join(batch)})
                )
            )["result"]
            rows = {}
            for row in data:
                symbol = row["symbol"]
                if symbol not in batch or symbol in rows:
                    raise s.DataError("unexpected_or_duplicate_detail")
                rows[symbol] = row
            return rows

        rows = attempt(issues, "stock", details) or {}
        for symbol in batch:
            stock_input = {
                "issues": list(issues),
                "earnings": {"status": "unconfirmed"},
            }
            inputs["stocks"][symbol] = {"inputs": stock_input}
            item = universe["symbols"][symbol]
            row = rows.get(symbol)
            if row is not None and symbol in REVIEWED_NON_COMMON:
                stock_input["stock_detail"] = row

                classification = attempt(
                    stock_input["issues"],
                    "security_classification",
                    partial(
                        classify_non_common,
                        read,
                        universe,
                        item,
                        row,
                        symbol,
                        as_of,
                        checked_at,
                    ),
                )
                if classification:
                    stock_input["security_classification"] = classification
                    stock_input["skipped"] = {
                        name: "verified_non_common_security"
                        for name in ("prices", "earnings", "turnover")
                    }
                    stock_input["collected_at"] = checked_at()
                    inputs["stocks"][symbol]["result"] = {
                        "status": "excluded",
                        "reasons": ["verified_non_common_security"],
                        "metrics": {},
                        "plan": None,
                    }
                    continue
            if row is None:
                stock_input["issues"].append("stock_detail_missing")
            elif symbol in universe["markets"][item["market"]]["conflicts"]:
                stock_input["issues"].append("stock_listing_conflict")
            elif (
                item.get("ambiguous")
                or row.get("market") != item["market"]
                or row.get("securityType") != item["listing"]["securityType"]
                or row.get("isCommonShare") is not True
                or row.get("status") != "ACTIVE"
                or row.get("currency") != "USD"
            ):
                stock_input["issues"].append("stock_identity_mismatch")
            else:
                stock_input["stock"] = row | {"toss_available": True}
            if cal is None:
                stock_input["issues"].extend(inputs["issues"])
            else:
                stock_input["calendar"] = cal
            evidence, result = s.collect_candidate(
                stock_input,
                read,
                report_day,
                as_of,
                earnings_sources.get(symbol),
                symbol,
                item["market"],
                execution="universe",
                checked_at=checked_at,
            )
            inputs["stocks"][symbol] = {"inputs": evidence, "result": result}
    return inputs


def finalize(inputs):
    """Return final per-stock decisions and their summary without changing collected inputs."""
    stocks = dict(inputs["stocks"])
    volume_ratios = {
        symbol: Decimal(row["result"]["metrics"]["volume_ratio"])
        for symbol, row in stocks.items()
        if row["result"]["status"] == "selected"
    }
    candidates = sorted(
        volume_ratios, key=lambda symbol: (-volume_ratios[symbol], symbol)
    )
    ratios = Counter(volume_ratios.values())
    unresolved = [symbol for symbol in candidates if ratios[volume_ratios[symbol]] > 1]
    # TODO: #233 - validate an exact consolidated turnover source before resolving tied ratios.
    for symbol in unresolved:
        result = stocks[symbol]["result"]
        stocks[symbol] = stocks[symbol] | {
            "result": result
            | {
                "status": "held",
                "plan": None,
                "reasons": result["reasons"] + ["exact_turnover_ranking_unavailable"],
            }
        }
    unresolved_set = set(unresolved)
    candidates = [symbol for symbol in candidates if symbol not in unresolved_set]
    status_counts = Counter(row["result"]["status"] for row in stocks.values())
    counts = {
        status: status_counts[status] for status in ("selected", "excluded", "held")
    }
    resolved = {
        symbol
        for symbol, row in stocks.items()
        if "security_classification" in row["inputs"]
    }
    coverage_issues = list(inputs["universe"]["issues"])
    for market, listing in inputs["universe"]["markets"].items():
        if (
            listing["conflicts"]
            and set(listing["conflicts"]) <= resolved
            and listing["issues"] == ["list_coverage_mismatch"]
            and listing["returned"]["all"]
        ):
            coverage_issues.remove(market + ":list_coverage_mismatch")
    evaluated_exclusion = counts["excluded"] > len(resolved) or (
        bool(stocks) and len(resolved) == len(stocks)
    )
    summary = {
        "status": "selected"
        if candidates
        else "excluded"
        if evaluated_exclusion
        else "held",
        "coverage_complete": not coverage_issues,
        "coverage_issues": coverage_issues,
        "verified_non_common": sorted(resolved),
        "ranking_complete": not unresolved,
        "ranking_held": unresolved,
        "collection_skipped": {
            name: sum(
                name in row["inputs"].get("skipped", {}) for row in stocks.values()
            )
            for name in ("earnings", "turnover")
        },
        "counts": {"total": len(stocks), **counts},
        "candidates": candidates[:3],
    }
    return inputs | {"stocks": stocks}, summary


def render(record):
    result, inputs = record["result"], record["inputs"]
    counts = result["counts"]
    labels = {
        "selected": "매수 후보 선정",
        "excluded": "검증된 범위의 조건 충족 후보 없음",
        "held": "전체 평가 불가",
    }
    lines = [
        "# 전체 종목군 개발 검증 보고서",
        "",
        f"자료 구분: {'검증용 사례' if record['synthetic'] else '실제 자동 수집 자료'}.",
        "",
        f"보고일: {record['report_date']}. 데이터 기준 시각: {record['as_of']}.",
        "",
        f"판정: {labels[result['status']]}.",
        "",
        f"순위 범위: {'검증된 후보' if result['ranking_complete'] else '순위 미확정 종목을 보류한 부분 범위'}.",
        "",
        f"전체 목록 범위: {'확보' if result['coverage_complete'] else '미확보'}. 공급자 내부 누락의 부재를 보장하지 않는다.",
        "",
        f"전체 {counts['total']}, 선정 {counts['selected']}, 제외 {counts['excluded']}, 보류 {counts['held']}.",
        "",
        f"실적 일정 조회 생략 {result['collection_skipped']['earnings']}종목. 거래대금 조회 생략 {result['collection_skipped']['turnover']}종목.",
        "",
        f"요청 {len(record['responses'])}회. 수집 소요 시간 {record['elapsed_seconds']}초.",
        "",
    ]
    for market, coverage in inputs["universe"]["markets"].items():
        lines += [
            f"- {market}: 확인 {len(coverage['symbols'])}종목. 반환 범위 {coverage['returned']}. 사유: {', '.join(coverage['issues']) or '대조 일치'}."
        ]
        lines += [
            f"  - {symbol}: {conflict['reason']}. 일반·유형별 원문은 기록에서 확인한다."
            for symbol, conflict in coverage["conflicts"].items()
        ]
    for symbol in result["verified_non_common"]:
        evidence = inputs["stocks"][symbol]["inputs"]["security_classification"]
        lines += [
            f"- {symbol}: 보통주 대상 아님({evidence['classification']}). ISIN {evidence['isin']}. "
            f"[발행사 근거]({evidence['source']}), 확인 {evidence['checked_at']}. 원본 목록 분류·충돌은 보존한다."
        ]
    lines += [
        "",
        "목록 미확보 사유: " + (", ".join(result["coverage_issues"]) or "없음") + ".",
        "",
    ]
    cal = inputs["calendar"]
    if cal:
        lines += [
            f"일봉 구간: {cal['past'][0]}~{cal['past'][-1]}. 실적 제외 구간: {cal['future'][0]}~{cal['future'][-1]}.",
            "",
        ]
    for rank, symbol in enumerate(result["candidates"], 1):
        row = inputs["stocks"][symbol]
        plan = {
            key: f"{Decimal(value):.2f}" for key, value in row["result"]["plan"].items()
        }
        metrics = row["result"]["metrics"]
        event = row["inputs"]["earnings"]
        lines += [
            f"## {rank}. {symbol}",
            "",
            f"선정 근거: {', '.join(row['result']['reasons'])}. 거래량 증가 배율 {metrics['volume_ratio']}, 평균 거래대금 하한 {metrics['average_turnover_lower_bound_usd']} USD.",
            "",
            f"전일 종가 기준 시가총액 {Decimal(metrics['market_cap_usd']):,.2f} USD. 돌파 기준선 {Decimal(metrics['breakout']):.2f} USD, 50일 이동평균 {Decimal(metrics['sma50']):.2f} USD, ATR(14) {Decimal(metrics['atr14']):.2f} USD.",
            "",
            f"다음 확정 실적: {event['date']}. [기업 공지]({event['source']}). 발행 시각: {event.get('published_at', '확인 불가')}.",
            "",
            f"진입 검토 구간: {plan['entry_low']}~{plan['entry_high']} USD = 전일 종가~전일 종가 + 0.5ATR. 구간 밖에서는 진입을 보류한다.",
            "",
            f"손실 제한 기준: {plan['stop']} USD = 돌파 기준선 − ATR. 예시 1R: {plan['risk']} USD = 전일 종가 − 손실 제한 기준.",
            "",
            f"예시 이익 실현 기준: {plan['target']} USD = 전일 종가 + 2R.",
            "",
        ]
    lines += [
        "진입 계획은 보고일 정규장 하루 동안 유효하다. 실제 진입가가 다르면 다시 계산한다. 실제 체결·최대 손실을 보장하지 않는다.",
        "",
        "가격은 KIS 원주가와 Yahoo 정규장 일봉을 대조한다. 현금배당은 소급 조정하지 않으며 분할 구간은 보류한다. 거래대금 하한은 정확한 전시장 평균이나 동순위 비교값이 아니다.",
        "",
        "제외·보류 사유별 건수(한 종목에 여러 사유가 있을 수 있다):",
        "",
        "| 판정 | 사유 | 종목 수 |",
        "| --- | --- | --- |",
    ]
    reasons = Counter(
        (row["result"]["status"], reason)
        for row in inputs["stocks"].values()
        if row["result"]["status"] != "selected"
        for reason in row["result"]["reasons"]
    )
    lines += [
        f"| {status} | {reason} | {count} |"
        for (status, reason), count in sorted(reasons.items())
    ]
    lines += [
        "",
        "조회 생략 항목과 사유(생략한 조건의 통과를 뜻하지 않는다):",
        "",
        "| 항목 | 사유 | 종목 수 |",
        "| --- | --- | --- |",
    ]
    skipped = Counter(
        (name, reason)
        for row in inputs["stocks"].values()
        for name, reason in row["inputs"].get("skipped", {}).items()
    )
    lines += [
        f"| {name} | {reason} | {count} |"
        for (name, reason), count in sorted(skipped.items())
    ]
    lines += [
        "",
        "[전체 종목별 판정·수집 응답·요청별 확인 시각](record.json)에 전체 근거를 보존한다.",
        "",
        "전체 목록 출처와 확인 시각:",
        "",
    ]
    lines += [
        f"- [{item['url']}]({item['url']}): {item['checked_at']} — {item.get('error', '수집됨')}"
        for item in record["responses"]
        if urlparse(item["url"]).path == "/api/v1/stocks/all"
    ]
    return "\n".join(lines) + "\n"


def code_hash():
    return records.code_hash((Path(__file__), Path(s.__file__), Path(ir.__file__)))


def run(
    output,
    report_day,
    *,
    fetch=s.fetch_public,
    now=None,
    synthetic=False,
    earnings_sources=None,
    clock=None,
):
    sources = checked_sources(earnings_sources)
    clock = clock or (lambda: now or datetime.now(UTC))
    as_of = clock()
    s.timestamp(as_of.isoformat())
    metadata = records.identity(
        RULES, (Path(__file__), Path(s.__file__), Path(ir.__file__)), CONTRACT
    )
    metadata.update(
        report_date=str(report_day),
        as_of=as_of.isoformat(),
        synthetic=synthetic,
        earnings_sources=sources,
    )
    execution = records.ExecutionRecord.start(output, metadata, fetch, clock)
    start = time.monotonic()
    with localcontext() as context:
        context.prec = 28
        inputs = collect(
            execution.read, report_day, as_of, sources, lambda: execution.checked_at
        )
        inputs, result = finalize(inputs)
    return execution.save(
        inputs, result, render, elapsed_seconds=round(time.monotonic() - start, 3)
    )


def replay(output):
    expected = records.identity(
        RULES, (Path(__file__), Path(s.__file__), Path(ir.__file__)), CONTRACT
    )
    execution = records.ExecutionRecord.load(output, expected)
    record = execution.record
    with localcontext() as context:
        context.prec = 28
        inputs = collect(
            execution.read,
            date.fromisoformat(record["report_date"]),
            s.timestamp(record["as_of"]),
            checked_sources(record["earnings_sources"]),
            lambda: execution.checked_at,
        )
        inputs, result = finalize(inputs)
    return execution.verify(inputs, result, render)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    live = sub.add_parser("run")
    live.add_argument("--output", type=Path, required=True)
    live.add_argument("--report-date", type=date.fromisoformat)
    live.add_argument("--credentials-file", type=Path)
    live.add_argument("--issue-tokens", action="store_true")
    live.add_argument(
        "--earnings-sources",
        type=Path,
        help="Public issuer source settings; no dates or credentials.",
    )
    saved = sub.add_parser("replay")
    saved.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "replay":
            record = replay(args.output)
        else:
            if args.output.exists():
                raise s.DataError("output_already_exists")
            credentials = s.credentials_for_run(
                args.credentials_file, args.issue_tokens
            )
            sources = checked_sources(
                json.loads(args.earnings_sources.read_text())
                if args.earnings_sources
                else None
            )
            hosts = tuple(
                {
                    urlparse(source[key]).netloc
                    for source in sources.values()
                    for key in ("listing_url", "article_prefix")
                }
                | {
                    urlparse(evidence["source"]).netloc
                    for evidence in REVIEWED_NON_COMMON.values()
                }
            )
            record = run(
                args.output,
                args.report_date or datetime.now(s.NY).date(),
                fetch=partial(
                    s.fetch_public, credentials=credentials, public_hosts=hosts
                ),
                earnings_sources=sources,
            )
        print(
            json.dumps(
                {"result": record["result"], "output": str(args.output)},
                ensure_ascii=False,
            )
        )
        return (
            0
            if args.command == "replay"
            or (
                record["result"]["coverage_complete"]
                and record["result"]["ranking_complete"]
                and record["result"]["status"] != "held"
            )
            else 2
        )
    except s.DataError as error:
        print("실행 또는 재현 실패: " + str(error))
    except OSError, ValueError, KeyError, TypeError, StopIteration:
        print("실행 또는 재현 실패. 입력·버전·기존 출력 경로를 확인하세요.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
