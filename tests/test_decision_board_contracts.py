from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]
from sab.decision_board.contracts import (
    ContractError,
    canonical_json_bytes,
    decision_payload_hash,
    load_decision_board_report,
    validate_claim_validation,
    validate_decision_board_report,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "decision_board"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "decision-board.v0.schema.json"
VALID_FIXTURES = ("published-entry.json", "published-holding.json", "blocked.json")
PUBLIC_URL_CORPUS = json.loads(
    (FIXTURE_DIR / "public-evidence-url-corpus.json").read_text(encoding="utf-8")
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _schema_validator() -> Any:
    from jsonschema import (  # type: ignore[import-untyped]
        Draft202012Validator,
        FormatChecker,
    )

    schema = _load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _definition_validator(definition: str) -> Any:
    from jsonschema import (  # type: ignore[import-untyped]
        Draft202012Validator,
        FormatChecker,
    )

    schema = _load_json(SCHEMA_PATH)
    return Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "$ref": f"#/$defs/{definition}",
        },
        format_checker=FormatChecker(),
    )


def _valid_claim() -> dict[str, Any]:
    instrument = _load_json(FIXTURE_DIR / "published-entry.json")["decision_payload"][
        "items"
    ][0]["instrument"]
    return {
        "claim_id": "claim-synthetic",
        "instrument": instrument,
        "source_url": "https://example.com/synthetic-claim",
        "publisher": "Synthetic Publisher",
        "published_at": "2026-08-06T00:30:00Z",
        "article_content_hash": (
            "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
        ),
        "supporting_span": "Synthetic exact supporting text.",
        "supporting_location": {
            "kind": "TEXT_OFFSETS",
            "start": 20,
            "end": 20,
        },
        "verifier_version": "fixture-verifier-v0",
        "entailment": "SUPPORTED",
    }


def test_jsonschema_format_checker_registers_required_formats() -> None:
    from jsonschema import FormatChecker  # type: ignore[import-untyped]

    checker = FormatChecker()

    assert "date-time" in checker.checkers
    assert "uri" in checker.checkers
    assert not checker.conforms("2026-02-30T01:00:05Z", "date-time")
    assert not checker.conforms("https://bad host.example/path", "uri")


@pytest.mark.parametrize("fixture_name", VALID_FIXTURES)
def test_golden_reports_pass_json_schema_and_python(fixture_name: str) -> None:
    path = FIXTURE_DIR / fixture_name
    report = _load_json(path)

    _schema_validator().validate(report)
    assert load_decision_board_report(path) == report
    assert validate_decision_board_report(report) == report


def test_invalid_golden_report_is_rejected_by_schema_and_python() -> None:
    report = _load_json(FIXTURE_DIR / "invalid-review-action.json")

    with pytest.raises(ValidationError):
        _schema_validator().validate(report)
    with pytest.raises(
        ContractError, match=r"\$\.decision_payload\.items\[0\]\.action"
    ):
        validate_decision_board_report(report)


def test_payload_hash_uses_canonical_payload_only() -> None:
    report = _load_json(FIXTURE_DIR / "published-entry.json")
    payload = report["decision_payload"]

    assert canonical_json_bytes(payload) == json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert decision_payload_hash(payload) == report["decision_payload_hash"]

    changed_envelope = copy.deepcopy(report)
    changed_envelope["metadata"] = {"compiler_version": "different"}
    changed_envelope["idempotency_key"] = "sha256:" + ("f" * 64)
    assert (
        decision_payload_hash(changed_envelope["decision_payload"])
        == report["decision_payload_hash"]
    )


@pytest.mark.parametrize("fixture_name", VALID_FIXTURES)
def test_golden_reports_require_canonical_idempotency_key(fixture_name: str) -> None:
    report = _load_json(FIXTURE_DIR / fixture_name)

    assert report["idempotency_key"].startswith("sha256:")
    assert len(report["idempotency_key"]) == 71
    assert validate_decision_board_report(report) == report


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="missing"),
        pytest.param("", id="blank"),
        pytest.param("sha256:" + ("A" * 64), id="uppercase"),
        pytest.param("sha256:" + ("a" * 63), id="short"),
        pytest.param(123, id="coerced-number"),
    ],
)
def test_envelope_rejects_noncanonical_idempotency_key(value: object) -> None:
    report = _load_json(FIXTURE_DIR / "published-entry.json")
    if value is None:
        report.pop("idempotency_key", None)
    else:
        report["idempotency_key"] = value

    with pytest.raises(ValidationError):
        _schema_validator().validate(report)
    with pytest.raises(ContractError, match=r"\$\.idempotency_key"):
        validate_decision_board_report(report)


def test_payload_hash_mismatch_is_rejected_with_a_useful_path() -> None:
    report = _load_json(FIXTURE_DIR / "published-entry.json")
    report["decision_payload"]["items"][0]["action"] = "AVOID"

    with pytest.raises(ContractError, match=r"\$\.decision_payload_hash"):
        validate_decision_board_report(report)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_loader_rejects_non_finite_json_constants(
    tmp_path: Path, constant: str
) -> None:
    report_path = tmp_path / "non-finite.json"
    report_path.write_text(
        f'{{"schema_version":"decision-board.v0","metadata":{{"value":{constant}}}}}',
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match="non-finite JSON constant"):
        load_decision_board_report(report_path)


@pytest.mark.parametrize(
    "invalid_json_value",
    [
        pytest.param(("tuple",), id="tuple"),
        pytest.param({1: "non-string key"}, id="non-string-key"),
        pytest.param(math.nan, id="nan"),
    ],
)
def test_direct_validator_rejects_non_json_metadata_values(
    invalid_json_value: object,
) -> None:
    report = _load_json(FIXTURE_DIR / "blocked.json")
    report["metadata"] = {"nested": invalid_json_value}

    with pytest.raises(ContractError, match=r"\$\.metadata"):
        validate_decision_board_report(report)


@pytest.mark.parametrize(
    "invalid_json_value",
    [
        pytest.param(("tuple",), id="tuple"),
        pytest.param({1: "non-string key"}, id="non-string-key"),
    ],
)
def test_canonical_json_rejects_values_that_json_dumps_would_coerce(
    invalid_json_value: object,
) -> None:
    with pytest.raises(ContractError, match="strict JSON"):
        canonical_json_bytes(invalid_json_value)


def test_cycles_are_typed_contract_errors_with_paths() -> None:
    cycle: dict[str, Any] = {}
    cycle["self"] = cycle
    report = _load_json(FIXTURE_DIR / "blocked.json")
    report["metadata"] = cycle

    with pytest.raises(ContractError, match=r"\$\.metadata\.self.*cycle"):
        validate_decision_board_report(report)
    with pytest.raises(ContractError, match=r"\$\.self.*cycle"):
        canonical_json_bytes(cycle)


@pytest.mark.parametrize(
    "invalid_value",
    [
        pytest.param({"text": "\ud800"}, id="string-value"),
        pytest.param({"\udfff": "text"}, id="object-key"),
    ],
)
def test_unpaired_surrogates_are_typed_contract_errors(
    invalid_value: dict[str, str],
) -> None:
    report = _load_json(FIXTURE_DIR / "blocked.json")
    report["metadata"] = invalid_value

    with pytest.raises(ContractError, match="Unicode scalar"):
        validate_decision_board_report(report)
    with pytest.raises(ContractError, match="Unicode scalar"):
        canonical_json_bytes(invalid_value)


def _mutate_blocked_with_payload(report: dict[str, Any]) -> None:
    report["status"] = "BLOCKED"
    report["issues"] = [{"code": "BLOCKED", "message": "Synthetic block."}]


def _mutate_decided_without_action(report: dict[str, Any]) -> None:
    del report["decision_payload"]["items"][0]["action"]


def _mutate_cross_kind_action(report: dict[str, Any]) -> None:
    report["decision_payload"]["items"][0]["action"] = "HOLD"


def _mutate_unsupported_evidence(report: dict[str, Any]) -> None:
    report["decision_payload"]["items"][0]["evidence"][0]["entailment"] = "UNCLEAR"


def _mutate_stale_payload_hash(report: dict[str, Any]) -> None:
    report["decision_payload"]["items"][0]["action"] = "AVOID"


@pytest.mark.parametrize(
    ("mutation", "schema_accepts"),
    [
        pytest.param(_mutate_blocked_with_payload, False, id="blocked-with-payload"),
        pytest.param(
            _mutate_decided_without_action, False, id="decided-without-action"
        ),
        pytest.param(_mutate_cross_kind_action, False, id="cross-kind-action"),
        pytest.param(_mutate_unsupported_evidence, False, id="unsupported-evidence"),
        pytest.param(_mutate_stale_payload_hash, True, id="stale-payload-hash"),
    ],
)
def test_mutation_corpus_is_rejected_at_the_applicable_contract_boundary(
    mutation: Any,
    schema_accepts: bool,
) -> None:
    report = _load_json(FIXTURE_DIR / "published-entry.json")
    mutation(report)

    if schema_accepts:
        _schema_validator().validate(report)
    else:
        with pytest.raises(ValidationError):
            _schema_validator().validate(report)
    with pytest.raises(ContractError):
        validate_decision_board_report(report)


def test_contracts_reject_unknown_fields() -> None:
    report = _load_json(FIXTURE_DIR / "blocked.json")
    report["unexpected"] = True
    with pytest.raises(ContractError, match=r"\$\.unexpected"):
        validate_decision_board_report(report)


@pytest.mark.parametrize(
    "timestamp",
    [
        pytest.param("2026-08-06T03:00:03", id="naive"),
        pytest.param("2026-02-30T03:00:03Z", id="impossible-calendar-date"),
    ],
)
def test_invalid_timestamp_mutations_fail_schema_and_consumers(timestamp: str) -> None:
    report = _load_json(FIXTURE_DIR / "blocked.json")
    report["created_at"] = timestamp

    with pytest.raises(ValidationError):
        _schema_validator().validate(report)
    with pytest.raises(ContractError, match=r"\$\.created_at"):
        validate_decision_board_report(report)


def test_timestamp_pattern_rejects_naive_values_without_format_checker() -> None:
    from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

    schema = _load_json(SCHEMA_PATH)
    report = _load_json(FIXTURE_DIR / "blocked.json")
    report["created_at"] = "2026-08-06T03:00:03"

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(report)


def test_empty_published_universe_is_valid() -> None:
    report = _load_json(FIXTURE_DIR / "published-entry.json")
    report["decision_payload"]["items"] = []
    report["decision_payload_hash"] = decision_payload_hash(report["decision_payload"])

    _schema_validator().validate(report)
    assert validate_decision_board_report(report) == report


@pytest.mark.parametrize(
    "source_url",
    [
        pytest.param("https://user:pass@example.com/article", id="userinfo"),
        pytest.param("https://localhost/article", id="localhost"),
        pytest.param("https://news.localhost/article", id="localhost-subdomain"),
        pytest.param("https://service.local/article", id="local-tld"),
        pytest.param("https://service.internal/article", id="internal-tld"),
        pytest.param("https://service.lan/article", id="lan-tld"),
        pytest.param("https://service.home/article", id="home-tld"),
        pytest.param("https://127.0.0.1/article", id="ipv4-loopback"),
        pytest.param("https://[::1]/article", id="ipv6-loopback"),
        pytest.param("https://192.168.1.1/article", id="ipv4-private"),
        pytest.param("https://169.254.169.254/latest", id="ipv4-link-local"),
        pytest.param("https://example.com:8443/article", id="nondefault-port"),
        pytest.param("https://example.com/article#private", id="fragment"),
        pytest.param("https://example.com/article?token=PRIVATE", id="query"),
        pytest.param("https://xn--pple-43d.com/article", id="punycode-label"),
        pytest.param("https://аpple.com/article", id="unicode-lookalike"),
        pytest.param("https://Example.com/article", id="noncanonical-case"),
        pytest.param("https://example.com", id="missing-canonical-slash"),
        pytest.param("https://example.com/" + ("a" * 2030), id="over-2048-bytes"),
        pytest.param("https://example.com./article", id="trailing-dot"),
        pytest.param("https://example.com/bad%", id="truncated-percent"),
        pytest.param("https://example.com/bad%2", id="short-percent"),
        pytest.param("https://example.com/bad%GG", id="nonhex-percent"),
        pytest.param("https://example.com/a[b", id="raw-open-bracket"),
        pytest.param("https://example.com/a]b", id="raw-close-bracket"),
        pytest.param("https://example.com/a|b", id="raw-pipe"),
        pytest.param("https://example.com/a{b", id="raw-open-brace"),
        pytest.param("https://example.com/a}b", id="raw-close-brace"),
        pytest.param("https://example.com/a^b", id="raw-caret"),
        pytest.param("https://example.com/a<b", id="raw-less-than"),
        pytest.param("https://example.com/a>b", id="raw-greater-than"),
        pytest.param(r"https://example.com/a\b", id="backslash"),
        pytest.param("https://example.com/café", id="non-ascii-path"),
    ],
)
def test_public_evidence_url_rejects_non_public_or_noncanonical_hosts(
    source_url: str,
) -> None:
    report = _load_json(FIXTURE_DIR / "published-entry.json")
    report["decision_payload"]["items"][0]["evidence"][0]["source_url"] = source_url
    report["decision_payload_hash"] = decision_payload_hash(report["decision_payload"])

    with pytest.raises(ValidationError):
        _schema_validator().validate(report)
    with pytest.raises(ContractError, match=r"source_url"):
        validate_decision_board_report(report)


@pytest.mark.parametrize(
    "source_url",
    [
        "https://example.com/",
        "https://example.com/a-z_A.Z~09",
        "https://example.com/!$&'()*+,;=:@/nested",
        "https://example.com/encoded%20space/%2F",
    ],
)
def test_public_evidence_url_accepts_conservative_rfc3986_paths(
    source_url: str,
) -> None:
    report = _load_json(FIXTURE_DIR / "published-entry.json")
    report["decision_payload"]["items"][0]["evidence"][0]["source_url"] = source_url
    report["decision_payload_hash"] = decision_payload_hash(report["decision_payload"])

    _schema_validator().validate(report)
    assert validate_decision_board_report(report) == report


@pytest.mark.parametrize("source_url", PUBLIC_URL_CORPUS["invalid"])
def test_shared_public_evidence_url_corpus_rejects_invalid_paths(
    source_url: str,
) -> None:
    report = _load_json(FIXTURE_DIR / "published-entry.json")
    report["decision_payload"]["items"][0]["evidence"][0]["source_url"] = source_url
    report["decision_payload_hash"] = decision_payload_hash(report["decision_payload"])

    with pytest.raises(ValidationError):
        _schema_validator().validate(report)
    with pytest.raises(ContractError):
        validate_decision_board_report(report)


@pytest.mark.parametrize("source_url", PUBLIC_URL_CORPUS["valid"])
def test_shared_public_evidence_url_corpus_accepts_valid_paths(
    source_url: str,
) -> None:
    report = _load_json(FIXTURE_DIR / "published-entry.json")
    report["decision_payload"]["items"][0]["evidence"][0]["source_url"] = source_url
    report["decision_payload_hash"] = decision_payload_hash(report["decision_payload"])

    _schema_validator().validate(report)
    assert validate_decision_board_report(report) == report


def test_evidence_reference_requires_exact_supported_claim_provenance() -> None:
    report = _load_json(FIXTURE_DIR / "published-entry.json")
    evidence = report["decision_payload"]["items"][0]["evidence"][0]
    required = {
        "entailment",
        "article_content_hash",
        "supporting_span",
        "supporting_location",
    }

    assert required <= evidence.keys()
    assert evidence["entailment"] == "SUPPORTED"
    assert evidence["supporting_location"] == {
        "kind": "TEXT_OFFSETS",
        "start": 0,
        "end": len(evidence["supporting_span"]),
    }

    for field in required:
        mutated = _load_json(FIXTURE_DIR / "published-entry.json")
        del mutated["decision_payload"]["items"][0]["evidence"][0][field]
        mutated["decision_payload_hash"] = decision_payload_hash(
            mutated["decision_payload"]
        )
        with pytest.raises((ValidationError, ContractError)):
            _schema_validator().validate(mutated)
            validate_decision_board_report(mutated)


def test_schema_exposes_all_normative_v0_contracts() -> None:
    schema = _load_json(SCHEMA_PATH)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("/decision-board.v0.schema.json")
    assert {
        "InstrumentRefV0",
        "BrokerSnapshotV0",
        "ClaimValidationV0",
        "DecisionInputV0",
        "DecisionItemV0",
        "DecisionPayloadV0",
        "DecisionBoardEnvelopeV0",
        "RunJournalV0",
    } <= schema["$defs"].keys()


def test_evidence_location_end_cannot_precede_start() -> None:
    claim = _valid_claim()
    claim["claim_id"] = "claim-invalid-offsets"
    claim["supporting_location"]["end"] = 19

    with pytest.raises(ContractError, match=r"\$\.supporting_location\.end"):
        validate_claim_validation(claim)

    claim["supporting_location"]["end"] = 20
    with pytest.raises(ContractError, match=r"\$\.supporting_location\.end"):
        validate_claim_validation(claim)

    claim["supporting_location"]["end"] = 21
    assert validate_claim_validation(claim) == claim


@pytest.mark.parametrize(
    "source_url",
    [
        pytest.param("mailto:research@example.com", id="non-http-scheme"),
        pytest.param("https://bad host.example/path", id="space-in-host"),
    ],
)
def test_source_url_mutations_fail_schema_and_consumers(source_url: str) -> None:
    claim = _valid_claim()
    claim["source_url"] = source_url

    with pytest.raises(ValidationError):
        _definition_validator("ClaimValidationV0").validate(claim)
    with pytest.raises(ContractError, match=r"\$\.source_url"):
        validate_claim_validation(claim)


def test_schema_documents_evidence_offset_consumer_invariant() -> None:
    schema = _load_json(SCHEMA_PATH)

    assert "end > start" in schema["$defs"]["SupportingLocationV0"]["$comment"]


def test_run_journal_allows_failed_without_directional_payload() -> None:
    schema = _load_json(SCHEMA_PATH)
    journal_schema = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": "#/$defs/RunJournalV0",
    }
    from jsonschema import (  # type: ignore[import-untyped]
        Draft202012Validator,
        FormatChecker,
    )

    journal = {
        "schema_version": "decision-board.v0",
        "run_id": "entry-2026-08-06T050000Z",
        "run_kind": "ENTRY",
        "status": "FAILED",
        "expected_at": "2026-08-06T05:00:00Z",
        "started_at": "2026-08-06T05:00:01Z",
        "terminal_at": "2026-08-06T05:00:02Z",
        "grace_seconds": 60,
        "stale_seconds": 300,
        "issues": [
            {
                "code": "COMPILER_CONTRACT_INVALID",
                "message": (
                    "Run reported sanitized issue code COMPILER_CONTRACT_INVALID."
                ),
            }
        ],
        "report_file": None,
    }

    Draft202012Validator(journal_schema, format_checker=FormatChecker()).validate(
        journal
    )
