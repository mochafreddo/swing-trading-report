"""Exploratory #233 listing comparison; never changes the production universe."""

import argparse
import copy
import csv
import hashlib
import io
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, build_opener

import single_run as s
import universe_run as u

DIRECTORIES = {
    "nasdaqlisted": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "otherlisted": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
}


def directory(body, kind):
    lines = body.splitlines()
    if not lines or not lines[-1].startswith("File Creation Time:"):
        raise ValueError("directory_footer_missing")
    key = "Symbol" if kind == "nasdaqlisted" else "ACT Symbol"
    records = list(csv.DictReader(io.StringIO("\n".join(lines[:-1])), delimiter="|"))
    if (
        not records
        or not {key, "Security Name", "ETF", "Test Issue"} <= records[0].keys()
    ):
        raise ValueError("directory_schema_invalid")
    result = {}
    for row in records:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("directory_row_invalid")
        symbol = row[key]
        if not symbol or symbol in result:
            raise ValueError("directory_duplicate_symbol")
        result[symbol] = row
    return result, lines[-1].split("|")[0]


def inspect_snapshot(record):
    lists, details, times = {}, {}, {}
    responses = {entry["url"]: entry for entry in record["responses"]}
    for entry in record["responses"]:
        url = urlsplit(entry["url"])
        if url.netloc != urlsplit(s.TOSS).netloc:
            continue
        if url.path not in {"/api/v1/stocks/all", "/api/v1/stocks"}:
            continue
        if entry.get("error"):
            raise ValueError("saved_listing_response_failed")
        rows = json.loads(entry["body"])["result"]
        if url.path == "/api/v1/stocks/all":
            query = parse_qs(url.query)
            pair = (query["market"][0], query.get("securityType", [""])[0])
            if pair in lists:
                raise ValueError("duplicate_saved_request")
            lists[pair] = {row["symbol"]: row for row in rows}
            if len(lists[pair]) != len(rows):
                raise ValueError("duplicate_saved_symbol")
            times["/".join(pair)] = entry["checked_at"]
        else:
            for row in rows:
                if row["symbol"] in details:
                    raise ValueError("duplicate_saved_detail")
                details[row["symbol"]] = row

    def read(url):
        entry = responses[url]
        if entry.get("error"):
            raise s.DataError("saved_response_failed")
        return entry["body"]

    discovered = u.discover(read)
    markets = {}
    for market in u.RULES["markets"]:
        general = {
            symbol: row
            for symbol, row in lists[market, ""].items()
            if row["securityType"] in u.RULES["types"]
        }
        typed = {
            symbol: row
            for kind in u.RULES["types"]
            for symbol, row in lists[market, kind].items()
        }
        conflicts = {
            symbol: details[symbol]
            for symbol in general.keys() | typed.keys()
            if symbol in details and details[symbol]["status"] != "ACTIVE"
        }
        markets[market] = {
            "general_stocks": len(general),
            "typed_stocks": len(typed),
            "general_only": sorted(general.keys() - typed.keys()),
            "typed_only": sorted(typed.keys() - general.keys()),
            "row_mismatches": sorted(
                symbol
                for symbol in general.keys() & typed.keys()
                if general[symbol] != typed[symbol]
            ),
            "detail_status_conflicts": conflicts,
        }
    return {
        "checked_at": times,
        "markets": markets,
        "production_discovery_issues": discovered["issues"],
    }


def comparison(snapshot, directory_responses):
    parsed = {
        kind: directory(entry["body"], kind)
        for kind, entry in directory_responses.items()
    }
    result = {}
    for market, rows in snapshot["markets"].items():
        symbols = sorted(
            set(rows["general_only"] + rows["typed_only"])
            | rows["detail_status_conflicts"].keys()
        )
        for symbol in symbols:
            result[symbol] = {
                "toss_market": market,
                "current_directory_rows": {
                    kind: data[0][symbol]
                    for kind, data in parsed.items()
                    if symbol in data[0]
                },
                "interpretation": "cross_time_observation_only_not_toss_tradability_proof",
            }
    return {
        "directory_rows": {kind: len(data[0]) for kind, data in parsed.items()},
        "creation_footers": {kind: data[1] for kind, data in parsed.items()},
        "conflict_symbols": result,
    }


def self_check(final_record):
    expected = ["CPOP", "HUBC", "IPDN", "KHC", "NFE", "NXXT", "PSNYW"]
    original = inspect_snapshot(final_record)
    assert original["markets"]["NASDAQ"]["general_only"] == expected
    assert len(original["markets"]["NASDAQ"]["detail_status_conflicts"]) == 6
    changed = copy.deepcopy(final_record)
    for entry in changed["responses"]:
        parsed = urlsplit(entry["url"])
        if parsed.path == "/api/v1/stocks/all" and parse_qs(parsed.query) == {
            "market": ["NASDAQ"],
            "status": ["ACTIVE"],
            "commonShare": ["true"],
        }:
            body = json.loads(entry["body"])
            body["result"] = [row for row in body["result"] if row["symbol"] != "AAPL"]
            entry["body"] = json.dumps(body)
    mutated = inspect_snapshot(changed)
    assert mutated["markets"]["NASDAQ"]["typed_only"] == ["AAPL"]
    # The same acceptance check must fail when a saved listing loses one row.
    try:
        assert mutated == original
    except AssertionError:
        pass
    else:
        raise AssertionError("omitted_listing_not_detected")
    sample = "Symbol|Security Name|ETF|Test Issue\nAAPL|Apple|N|N\nFile Creation Time: 0914202621:31||||\n"
    assert directory(sample, "nasdaqlisted")[0]["AAPL"]["ETF"] == "N"
    for bad in [
        sample.split("File Creation")[0],
        sample.replace("File Creation", "AAPL|Apple|N|N\nFile Creation"),
    ]:
        try:
            directory(bad, "nasdaqlisted")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid_directory_accepted")
    return {
        "baseline_conflicts": 7,
        "detail_conflicts": 6,
        "negative_controls_detected": [
            "omitted_AAPL",
            "missing_footer",
            "duplicate_symbol",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--directories-from",
        type=Path,
        help="Replay saved public directory responses offline",
    )
    args = parser.parse_args()
    loaded = [(path, json.loads(path.read_text())) for path in args.records]
    snapshots = [
        {
            "source": str(path),
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "analysis": inspect_snapshot(record),
        }
        for path, record in loaded
    ]
    checks = self_check(loaded[-1][1])
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    if args.directories_from:
        saved = json.loads(args.directories_from.read_text())
        responses = saved["directory_responses"]
        for entry in responses.values():
            assert hashlib.sha256(entry["body"].encode()).hexdigest() == entry["sha256"]
    else:
        responses = {}
        for kind, url in DIRECTORIES.items():
            request = Request(
                url, headers={"User-Agent": "swing-trading-report-data-probe/0.1"}
            )
            with build_opener(s.NoRedirect).open(request, timeout=30) as response:
                raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise ValueError("directory_response_too_large")
            body = raw.decode("utf-8")
            responses[kind] = {
                "url": url,
                "checked_at": datetime.now(UTC).isoformat(),
                "body": body,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
    result = {
        "snapshots": snapshots,
        "directory_responses": responses,
        "comparison": comparison(snapshots[-1]["analysis"], responses),
        "checks": checks,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "network_requests": 0 if args.directories_from else len(responses),
    }
    (args.output / "record.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    summary = {
        key: value for key, value in result.items() if key != "directory_responses"
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "checks": checks,
                "conflict_symbols": sorted(result["comparison"]["conflict_symbols"]),
                "network_requests": result["network_requests"],
                "elapsed_seconds": result["elapsed_seconds"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
