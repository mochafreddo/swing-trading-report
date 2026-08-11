from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sab.decision_board.compiler import (
    ApprovalStateV0,
    DecisionCompilerV0,
    DependencyStateV0,
    EntryCompilerItemV0,
    EntrySignalStateV0,
    ExposureStateV0,
    HardExitStateV0,
    HoldingCompilerItemV0,
    ResearchStateV0,
)
from sab.decision_board.contracts import canonical_json_bytes
from sab.decision_board.instruments import InstrumentRefV0
from sab.decision_board.policy import select_holding_research_v0
from sab.decision_board.results import (
    DECISION_RUN_FAILED_EXIT_CODE,
    DecisionRunBlockedV0,
    DecisionRunFailedV0,
    DecisionRunIssueCodeV0,
    DecisionRunPublishedV0,
    create_decision_run_failed_v0,
    create_decision_run_published_v0,
    decision_run_exit_code_v0,
    serialize_decision_run_result_v0,
)
from sab.decision_board.runner import (
    CompilerItemV0,
    DecisionBoardRunnerV0,
    DecisionItemEnrichmentOperationalError,
    DecisionRunRequestV0,
    RunKindV0,
    UploadModeV0,
    create_decision_run_request_v0,
    create_run_prepared_v0,
    create_run_shared_blocked_v0,
)
from sab.report.decision_board import (
    build_decision_board_storage_key,
    write_decision_board_report,
)


def _instrument():
    return InstrumentRefV0(
        market="US",
        canonical_ticker="AAPL",
        exchange="NASDAQ",
        company_name="Apple Synthetic",
        identity_source="synthetic-registry",
        identity_version="2026-08-09",
    )


def _entry_item(*, item_id: str = "entry-AAPL") -> EntryCompilerItemV0:
    return EntryCompilerItemV0.create(
        item_id=item_id,
        instrument=_instrument(),
        item_state=ApprovalStateV0.APPROVED,
        identity_state=ApprovalStateV0.APPROVED,
        signal_state=EntrySignalStateV0.READY_ENTER,
        mandate_state=DependencyStateV0.CURRENT,
        price_state=DependencyStateV0.CURRENT,
        exposure_state=ExposureStateV0.PASS,
        research_state=ResearchStateV0.CLEAR,
    )


def _numbered_instrument(index: int) -> InstrumentRefV0:
    return InstrumentRefV0(
        market="US",
        canonical_ticker=f"SYN{index}.NAS",
        exchange="NASDAQ",
        company_name=f"Synthetic Company {index}",
        identity_source="synthetic-registry",
        identity_version="2026-08-09",
    )


def _numbered_entry(index: int) -> EntryCompilerItemV0:
    return EntryCompilerItemV0.create(
        item_id=f"entry-SYN{index}.NAS",
        instrument=_numbered_instrument(index),
        item_state=ApprovalStateV0.APPROVED,
        identity_state=ApprovalStateV0.APPROVED,
        signal_state=EntrySignalStateV0.READY_ENTER,
        mandate_state=DependencyStateV0.CURRENT,
        price_state=DependencyStateV0.CURRENT,
        exposure_state=ExposureStateV0.PASS,
        research_state=ResearchStateV0.CLEAR,
    )


def _holding(index: int, *, hard_exit: HardExitStateV0 = HardExitStateV0.NONE):
    return HoldingCompilerItemV0.create(
        item_id=f"holding-SYN{index}.NAS",
        instrument=_numbered_instrument(index),
        item_state=ApprovalStateV0.APPROVED,
        identity_state=ApprovalStateV0.APPROVED,
        hard_exit_state=hard_exit,
        broker_state=DependencyStateV0.CURRENT,
        candle_state=DependencyStateV0.CURRENT,
        rule_state=DependencyStateV0.CURRENT,
        research_state=ResearchStateV0.CLEAR,
        research_priority=index,
        research_order=f"order-{index:02d}",
    )


def _holding_request(items, **overrides: object):
    selection = select_holding_research_v0(items)
    values = {
        "run_kind": RunKindV0.HOLDING,
        "run_id": "holding-shadow-001",
        "idempotency_key": "sha256:" + "7" * 64,
        "created_at": datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        "sealed_input_hash": "sha256:" + "8" * 64,
        "items": items,
        "selection": selection,
        "upload_mode": UploadModeV0.DISABLED,
        "metadata": {
            "policy_version": "decision-policy.v0",
            "eligible_count": len(items),
        },
    }
    values.update(overrides)
    return create_decision_run_request_v0(**values)


def _request(**overrides: object) -> DecisionRunRequestV0:
    values = {
        "run_kind": RunKindV0.ENTRY,
        "run_id": "entry-shadow-001",
        "idempotency_key": "sha256:" + "1" * 64,
        "created_at": datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        "sealed_input_hash": "sha256:" + "2" * 64,
        "items": (_entry_item(),),
        "selection": None,
        "upload_mode": UploadModeV0.DISABLED,
        "metadata": {"policy_version": "decision-policy.v0", "eligible_count": 1},
    }
    values.update(overrides)
    return create_decision_run_request_v0(**values)  # type: ignore[arg-type]


class _Prepared:
    def prepare(self, request: DecisionRunRequestV0):
        return create_run_prepared_v0(request)


class _Blocked:
    def prepare(self, request: DecisionRunRequestV0):
        del request
        return create_run_shared_blocked_v0(
            DecisionRunIssueCodeV0.SHARED_PREFLIGHT_UNAVAILABLE
        )


class _CopyEnricher:
    def enrich(self, item: CompilerItemV0, *, request: object):
        assert type(item) is EntryCompilerItemV0
        assert "account" not in repr(request).lower()
        return EntryCompilerItemV0.create(
            item_id=item.item_id,
            instrument=item.instrument,
            item_state=item.item_state,
            identity_state=item.identity_state,
            signal_state=item.signal_state,
            mandate_state=item.mandate_state,
            price_state=item.price_state,
            exposure_state=item.exposure_state,
            research_state=item.research_state,
            evidence=item.evidence,
        )


class _HoldingCopyEnricher:
    def enrich(self, item: CompilerItemV0, *, request: object):
        assert type(item) is HoldingCompilerItemV0
        assert "account" not in repr(request).lower()
        return HoldingCompilerItemV0.create(
            item_id=item.item_id,
            instrument=item.instrument,
            item_state=item.item_state,
            identity_state=item.identity_state,
            hard_exit_state=item.hard_exit_state,
            broker_state=item.broker_state,
            candle_state=item.candle_state,
            rule_state=item.rule_state,
            research_state=item.research_state,
            research_priority=item.research_priority,
            research_order=item.research_order,
            evidence=item.evidence,
        )


def test_request_is_factory_owned_and_rejects_raw_fresh_equal_and_mutation() -> None:
    issued = _request()
    assert issued.run_kind is RunKindV0.ENTRY

    with pytest.raises(TypeError):
        DecisionRunRequestV0()  # type: ignore[call-arg]

    raw = object.__new__(DecisionRunRequestV0)
    for name in (
        "run_kind",
        "run_id",
        "idempotency_key",
        "created_at",
        "sealed_input_hash",
        "items",
        "selection",
        "upload_mode",
        "metadata",
    ):
        object.__setattr__(raw, name, getattr(issued, name))
    with pytest.raises(TypeError, match="issued"):
        create_decision_run_request_v0(existing=raw)

    fresh_equal_item = _entry_item()
    with pytest.raises(TypeError, match="unchanged issued"):
        create_decision_run_request_v0(
            existing=issued,
            items=(fresh_equal_item,),
        )

    object.__setattr__(issued, "run_id", "mutated")
    with pytest.raises(TypeError, match="unchanged issued"):
        create_decision_run_request_v0(existing=issued)


def test_request_rejects_cross_lane_selection_and_private_metadata() -> None:
    with pytest.raises(ValueError, match=r"ENTRY.*selection"):
        _request(selection=object())
    with pytest.raises(ValueError, match="metadata"):
        _request(metadata={"account_id": "PRIVATE-SENTINEL"})


@pytest.mark.parametrize(
    "version",
    ["/private/model-v1", "model\nPRIVATE-SENTINEL", "secret-token-v1"],
)
def test_request_rejects_path_control_and_private_version_metadata(
    version: str,
) -> None:
    with pytest.raises(ValueError, match="metadata"):
        _request(metadata={"researcher_version": version})


def test_request_derives_run_counts_and_rejects_count_lies() -> None:
    request = _request(metadata={"policy_version": "decision-policy.v0"})
    assert request.metadata == {
        "eligible_count": 1,
        "policy_version": "decision-policy.v0",
        "selected_count": 1,
    }

    with pytest.raises(ValueError, match="metadata"):
        _request(metadata={"eligible_count": 999, "selected_count": 0})

    holdings = (_holding(1), _holding(2))
    holding_request = _holding_request(
        holdings,
        metadata={"registry_version": "registry-v1"},
    )
    assert holding_request.metadata["eligible_count"] == 2
    assert holding_request.metadata["selected_count"] == len(
        holding_request.selection.selected_item_ids
    )


def test_failed_result_is_closed_exact_and_serializes_only_public_allowlist() -> None:
    result = create_decision_run_failed_v0(
        issue_code=DecisionRunIssueCodeV0.CONFIG_UNAVAILABLE,
    )
    assert decision_run_exit_code_v0(result) == DECISION_RUN_FAILED_EXIT_CODE
    assert serialize_decision_run_result_v0(result) == {
        "status": "FAILED",
        "exit_code": DECISION_RUN_FAILED_EXIT_CODE,
        "issue_code": "CONFIG_UNAVAILABLE",
    }

    with pytest.raises(TypeError):
        type(result)()  # type: ignore[call-arg]

    forged = object.__new__(type(result))
    object.__setattr__(forged, "issue_code", result.issue_code)
    object.__setattr__(forged, "local_path", "/private/PRIVATE-SENTINEL.json")
    with pytest.raises(TypeError, match="issued"):
        serialize_decision_run_result_v0(forged)

    object.__setattr__(result, "issue_code", DecisionRunIssueCodeV0.INTERNAL_ERROR)
    with pytest.raises(TypeError, match="unchanged issued"):
        serialize_decision_run_result_v0(result)


def test_result_factories_bind_exact_t7_identity_and_compatible_fields(
    tmp_path,
) -> None:
    stored = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
    ).run(_request())
    assert type(stored) is DecisionRunPublishedV0
    exact_key = build_decision_board_storage_key(stored.envelope)

    with pytest.raises(ValueError):
        create_decision_run_published_v0(
            envelope=stored.envelope,
            local_path=stored.local_path,
            storage_key="foreign/key.json",
        )
    with pytest.raises(ValueError):
        create_decision_run_published_v0(
            envelope=stored.envelope,
            local_path=stored.local_path,
            storage_key=exact_key,
            upload_issue=DecisionRunIssueCodeV0.UPLOAD_FAILED,
        )
    with pytest.raises((TypeError, ValueError)):
        create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.CONFIG_UNAVAILABLE,
            local_path=stored.local_path,
            retained_envelope=stored.envelope,
        )
    with pytest.raises((TypeError, ValueError)):
        create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.UPLOAD_FAILED,
        )

    retained = create_decision_run_failed_v0(
        issue_code=DecisionRunIssueCodeV0.UPLOAD_FAILED,
        local_path=stored.local_path,
        retained_envelope=stored.envelope,
    )
    assert serialize_decision_run_result_v0(retained)["report_file"] == (
        stored.local_path.name
    )


def test_result_serializer_contains_mutated_path_runtime_error(tmp_path) -> None:
    stored = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
    ).run(_request())
    assert type(stored) is DecisionRunPublishedV0

    class _EvilPath(type(stored.local_path)):  # type: ignore[misc]
        def read_bytes(self):
            raise RuntimeError("PRIVATE-SENTINEL path")

    object.__setattr__(stored, "local_path", _EvilPath(stored.local_path))
    with pytest.raises(TypeError) as exc_info:
        serialize_decision_run_result_v0(stored)
    assert "PRIVATE-SENTINEL" not in str(exc_info.value)


@pytest.mark.parametrize("variant", ["published", "failed"])
def test_result_serializer_rejects_status_subclass_and_runtime_error(
    tmp_path, variant: str
) -> None:
    result = (
        DecisionBoardRunnerV0(
            preparer=_Prepared(),
            enricher=_CopyEnricher(),
            report_dir=tmp_path,
        ).run(_request())
        if variant == "published"
        else create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.INTERNAL_ERROR
        )
    )

    class _EvilStatus(str):
        def __hash__(self):
            raise RuntimeError("PRIVATE-SENTINEL status")

    object.__setattr__(result, "status", _EvilStatus(result.status))
    with pytest.raises(TypeError) as exc_info:
        serialize_decision_run_result_v0(result)
    assert "PRIVATE-SENTINEL" not in str(exc_info.value)


def test_published_and_blocked_are_success_exit_states_with_exact_envelopes(
    tmp_path,
) -> None:
    published = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
    ).run(_request())
    assert type(published) is DecisionRunPublishedV0
    assert decision_run_exit_code_v0(published) == 0
    assert published.envelope["status"] == "PUBLISHED"
    assert published.envelope["decision_payload_hash"].startswith("sha256:")
    assert published.local_path.is_file()
    assert serialize_decision_run_result_v0(published) == {
        "status": "PUBLISHED",
        "exit_code": 0,
        "report_file": published.local_path.name,
        "storage_key": None,
        "degraded": False,
    }
    object.__setattr__(published, "storage_key", "forged/private-key")
    with pytest.raises(TypeError, match="unchanged issued"):
        serialize_decision_run_result_v0(published)

    blocked = DecisionBoardRunnerV0(
        preparer=_Blocked(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
    ).run(
        _request(
            run_id="entry-shadow-blocked",
            idempotency_key="sha256:" + "3" * 64,
        )
    )
    assert type(blocked) is DecisionRunBlockedV0
    assert decision_run_exit_code_v0(blocked) == 0
    assert blocked.envelope["status"] == "BLOCKED"
    assert "decision_payload" not in blocked.envelope
    assert blocked.envelope["issues"] == [
        {
            "code": "SHARED_PREFLIGHT_UNAVAILABLE",
            "message": "A shared Decision Board prerequisite is unavailable.",
        }
    ]


def test_mutated_preparation_result_is_failed_without_write(tmp_path) -> None:
    class _MutatedPreparation:
        def prepare(self, request):
            del request
            result = create_run_shared_blocked_v0(
                DecisionRunIssueCodeV0.SHARED_PREFLIGHT_UNAVAILABLE
            )
            object.__setattr__(
                result,
                "issue_codes",
                (DecisionRunIssueCodeV0.INTERNAL_ERROR,),
            )
            return result

    result = DecisionBoardRunnerV0(
        preparer=_MutatedPreparation(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
    ).run(_request())
    assert serialize_decision_run_result_v0(result)["issue_code"] == (
        "PREPARATION_INVALID"
    )
    assert list(tmp_path.glob("*.json")) == []


def test_all_review_and_empty_no_signal_entry_remain_published(tmp_path) -> None:
    timeout_item = _entry_item()

    class _TimeoutEnricher(_CopyEnricher):
        def enrich(self, item: CompilerItemV0, *, request: object):
            del request
            assert type(item) is EntryCompilerItemV0
            return EntryCompilerItemV0.create(
                item_id=item.item_id,
                instrument=item.instrument,
                item_state=item.item_state,
                identity_state=item.identity_state,
                signal_state=item.signal_state,
                mandate_state=item.mandate_state,
                price_state=item.price_state,
                exposure_state=item.exposure_state,
                research_state=ResearchStateV0.TIMEOUT,
                evidence=(),
            )

    all_review = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_TimeoutEnricher(),
        report_dir=tmp_path,
    ).run(
        _request(
            run_id="entry-all-review",
            idempotency_key="sha256:" + "4" * 64,
            items=(timeout_item,),
        )
    )
    assert type(all_review) is DecisionRunPublishedV0
    assert all_review.envelope["decision_payload"]["items"][0]["status"] == "REVIEW"

    absent = EntryCompilerItemV0.create(
        item_id="entry-AAPL",
        instrument=_instrument(),
        item_state=ApprovalStateV0.APPROVED,
        identity_state=ApprovalStateV0.APPROVED,
        signal_state=EntrySignalStateV0.ABSENT,
        mandate_state=DependencyStateV0.CURRENT,
        price_state=DependencyStateV0.CURRENT,
        exposure_state=ExposureStateV0.PASS,
        research_state=ResearchStateV0.CLEAR,
    )
    empty = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
    ).run(
        _request(
            run_id="entry-empty",
            idempotency_key="sha256:" + "5" * 64,
            items=(absent,),
        )
    )
    assert type(empty) is DecisionRunPublishedV0
    assert empty.envelope["decision_payload"]["items"] == []


def test_local_write_precedes_upload_and_exact_replay_returns_same_keys(
    tmp_path,
) -> None:
    events: list[str] = []

    def local_writer(report: object, *, report_dir):
        events.append("local")
        return write_decision_board_report(report, report_dir=report_dir)

    class _Uploader:
        def upload(self, *, local_path, storage_key):
            assert local_path.is_file()
            events.append("upload")
            return storage_key

    runner = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
        local_writer=local_writer,
        uploader=_Uploader(),
    )
    request = _request(upload_mode=UploadModeV0.OPTIONAL)
    first = runner.run(request)
    second = runner.run(request)

    assert type(first) is DecisionRunPublishedV0
    assert type(second) is DecisionRunPublishedV0
    assert events == ["local", "upload", "local", "upload"]
    assert first.local_path == second.local_path
    assert first.storage_key == second.storage_key
    assert first.local_path.read_bytes() == second.local_path.read_bytes()


def test_optional_and_required_upload_failure_preserve_local_contract(tmp_path) -> None:
    class _FailingUploader:
        def upload(self, *, local_path, storage_key):
            del local_path, storage_key
            raise RuntimeError("PRIVATE-SENTINEL provider response")

    optional = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
        uploader=_FailingUploader(),
    ).run(_request(upload_mode=UploadModeV0.OPTIONAL))
    assert type(optional) is DecisionRunPublishedV0
    assert optional.local_path.is_file()
    assert optional.storage_key is None
    assert serialize_decision_run_result_v0(optional)["upload_issue"] == "UPLOAD_FAILED"
    assert "PRIVATE-SENTINEL" not in repr(serialize_decision_run_result_v0(optional))

    required = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
        uploader=_FailingUploader(),
    ).run(
        _request(
            run_id="entry-upload-required",
            idempotency_key="sha256:" + "6" * 64,
            upload_mode=UploadModeV0.REQUIRED,
        )
    )
    assert type(required) is DecisionRunFailedV0
    assert required.local_path is not None
    retained_path = required.local_path
    summary = serialize_decision_run_result_v0(required)
    assert summary == {
        "status": "FAILED",
        "exit_code": DECISION_RUN_FAILED_EXIT_CODE,
        "issue_code": "UPLOAD_FAILED",
        "report_file": retained_path.name,
    }
    assert retained_path.is_file()


def test_local_failure_and_idempotency_conflict_never_upload(tmp_path) -> None:
    uploads: list[str] = []

    class _Uploader:
        def upload(self, *, local_path, storage_key):
            del local_path
            uploads.append(storage_key)
            return storage_key

    def failed_writer(report: object, *, report_dir):
        del report, report_dir
        raise OSError("PRIVATE-SENTINEL disk")

    failed = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
        uploader=_Uploader(),
        local_writer=failed_writer,
    ).run(_request(upload_mode=UploadModeV0.REQUIRED))
    assert serialize_decision_run_result_v0(failed)["issue_code"] == (
        "LOCAL_PERSISTENCE_FAILED"
    )
    assert uploads == []

    runner = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
        uploader=_Uploader(),
    )
    first = runner.run(_request(upload_mode=UploadModeV0.OPTIONAL))
    assert type(first) is DecisionRunPublishedV0
    conflict = runner.run(
        _request(
            upload_mode=UploadModeV0.OPTIONAL,
            metadata={"policy_version": "different-policy", "eligible_count": 1},
        )
    )
    assert serialize_decision_run_result_v0(conflict)["issue_code"] == (
        "IDEMPOTENCY_CONFLICT"
    )
    assert len(uploads) == 1


def test_persistence_boundary_contains_runtime_error_and_rejects_string_subclass(
    tmp_path,
) -> None:
    uploads: list[str] = []

    class _EqualString(str):
        pass

    class _Uploader:
        def upload(self, *, local_path, storage_key):
            assert local_path.is_file()
            uploads.append(storage_key)
            return _EqualString(storage_key)

    def failed_writer(report: object, *, report_dir):
        del report, report_dir
        raise RuntimeError("PRIVATE-SENTINEL local writer")

    local_failed = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
        uploader=_Uploader(),
        local_writer=failed_writer,
    ).run(_request(upload_mode=UploadModeV0.REQUIRED))
    assert serialize_decision_run_result_v0(local_failed)["issue_code"] == (
        "LOCAL_PERSISTENCE_FAILED"
    )
    assert uploads == []

    optional = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
        uploader=_Uploader(),
    ).run(
        _request(
            run_id="entry-equal-string",
            idempotency_key="sha256:" + "a" * 64,
            upload_mode=UploadModeV0.OPTIONAL,
        )
    )
    assert type(optional) is DecisionRunPublishedV0
    assert optional.storage_key is None
    assert serialize_decision_run_result_v0(optional)["upload_issue"] == "UPLOAD_FAILED"


@pytest.mark.parametrize("upload_mode", [UploadModeV0.OPTIONAL, UploadModeV0.REQUIRED])
def test_upload_failure_restores_uploader_deleted_local_artifact(
    tmp_path, upload_mode: UploadModeV0
) -> None:
    class _DeletingUploader:
        def upload(self, *, local_path, storage_key):
            del storage_key
            local_path.unlink()
            raise RuntimeError("PRIVATE-SENTINEL uploader")

    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
        uploader=_DeletingUploader(),
    ).run(
        _request(
            run_id=f"entry-delete-{upload_mode.value.lower()}",
            idempotency_key=(
                "sha256:" + ("3" if upload_mode is UploadModeV0.OPTIONAL else "4") * 64
            ),
            upload_mode=upload_mode,
        )
    )

    public = serialize_decision_run_result_v0(result)
    if upload_mode is UploadModeV0.OPTIONAL:
        assert public["status"] == "PUBLISHED"
        assert public["upload_issue"] == "UPLOAD_FAILED"
    else:
        assert public["issue_code"] == "UPLOAD_FAILED"
    report_file = public["report_file"]
    assert type(report_file) is str
    assert (tmp_path / report_file).is_file()
    assert "PRIVATE-SENTINEL" not in repr(public)


def test_uploader_cannot_downgrade_required_mode_after_local_write(tmp_path) -> None:
    request = _request(
        run_id="entry-required-mode-mutation",
        idempotency_key="sha256:" + "5" * 64,
        upload_mode=UploadModeV0.REQUIRED,
    )

    class _MutatingUploader:
        def upload(self, *, local_path, storage_key):
            del local_path, storage_key
            object.__setattr__(request, "upload_mode", UploadModeV0.OPTIONAL)
            raise RuntimeError("PRIVATE-SENTINEL uploader")

    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
        uploader=_MutatingUploader(),
    ).run(request)

    public = serialize_decision_run_result_v0(result)
    assert public["status"] == "FAILED"
    assert public["issue_code"] == "UPLOAD_FAILED"
    report_file = public["report_file"]
    assert type(report_file) is str
    assert (tmp_path / report_file).is_file()
    assert "PRIVATE-SENTINEL" not in repr(public)


def test_symlink_report_directory_is_rejected_before_injected_writer(tmp_path) -> None:
    real_directory = tmp_path / "outside"
    real_directory.mkdir()
    report_directory = tmp_path / "reports-link"
    report_directory.symlink_to(real_directory, target_is_directory=True)
    writes: list[object] = []

    def unsafe_writer(report: object, *, report_dir):
        writes.append(report)
        key = build_decision_board_storage_key(report)
        path = report_dir / key.rsplit("/", 1)[-1]
        path.write_bytes(canonical_json_bytes(report))
        return path

    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=report_directory,
        local_writer=unsafe_writer,
    ).run(_request())

    assert serialize_decision_run_result_v0(result)["issue_code"] == (
        "LOCAL_PERSISTENCE_FAILED"
    )
    assert writes == []
    assert list(real_directory.iterdir()) == []


def test_report_directory_inode_swap_during_writer_is_rejected(tmp_path) -> None:
    report_directory = tmp_path / "reports"
    report_directory.mkdir()
    original_directory = tmp_path / "reports-original"
    outside_directory = tmp_path / "outside"
    outside_directory.mkdir()

    def swapping_writer(report: object, *, report_dir):
        report_dir.rename(original_directory)
        report_dir.symlink_to(outside_directory, target_is_directory=True)
        key = build_decision_board_storage_key(report)
        path = report_dir / key.rsplit("/", 1)[-1]
        path.write_bytes(canonical_json_bytes(report))
        return path

    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=report_directory,
        local_writer=swapping_writer,
    ).run(_request())

    assert serialize_decision_run_result_v0(result)["issue_code"] == (
        "LOCAL_PERSISTENCE_FAILED"
    )


def test_invalid_compiler_payload_is_failed_before_any_write(
    tmp_path, monkeypatch
) -> None:
    writes: list[object] = []

    def writer(report: object, *, report_dir):
        del report_dir
        writes.append(report)
        raise AssertionError("writer must not be called")

    monkeypatch.setattr(
        "sab.decision_board.runner.DecisionCompilerV0.compile_entry",
        lambda *args, **kwargs: {"run_kind": "ENTRY", "items": "invalid"},
    )
    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
        local_writer=writer,
    ).run(_request())
    assert serialize_decision_run_result_v0(result)["issue_code"] == (
        "COMPILER_CONTRACT_INVALID"
    )
    assert writes == []


def test_operational_item_timeout_isolated_while_peer_decides(tmp_path) -> None:
    items = (_numbered_entry(1), _numbered_entry(2))

    class _OneTimeout(_CopyEnricher):
        def enrich(self, item, *, request):
            if item.item_id == "entry-SYN1.NAS":
                raise DecisionItemEnrichmentOperationalError(ResearchStateV0.TIMEOUT)
            return EntryCompilerItemV0.create(
                item_id=item.item_id,
                instrument=item.instrument,
                item_state=item.item_state,
                identity_state=item.identity_state,
                signal_state=item.signal_state,
                mandate_state=item.mandate_state,
                price_state=item.price_state,
                exposure_state=item.exposure_state,
                research_state=ResearchStateV0.CLEAR,
            )

    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_OneTimeout(),
        report_dir=tmp_path,
    ).run(
        _request(
            run_id="entry-isolation",
            idempotency_key="sha256:" + "9" * 64,
            items=items,
            metadata={"eligible_count": 2},
        )
    )
    assert type(result) is DecisionRunPublishedV0
    rows = result.envelope["decision_payload"]["items"]
    assert [(row["instrument"]["canonical_ticker"], row["status"]) for row in rows] == [
        ("SYN1.NAS", "REVIEW"),
        ("SYN2.NAS", "DECIDED"),
    ]


@pytest.mark.parametrize("attack", ["mutated", "subclass"])
def test_operational_error_requires_exact_unchanged_issuance(
    tmp_path, attack: str
) -> None:
    class _OperationalSubclass(DecisionItemEnrichmentOperationalError):
        pass

    class _Attacker:
        def enrich(self, item, *, request):
            del item, request
            if attack == "subclass":
                raise _OperationalSubclass(ResearchStateV0.TIMEOUT)
            error = DecisionItemEnrichmentOperationalError(ResearchStateV0.TIMEOUT)
            error.research_state = ResearchStateV0.CLEAR
            raise error

    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_Attacker(),
        report_dir=tmp_path,
    ).run(_request())
    assert serialize_decision_run_result_v0(result)["issue_code"] == (
        "ITEM_ENRICHMENT_INVALID"
    )
    assert list(tmp_path.glob("*.json")) == []


def test_unexpected_item_adapter_error_is_failed_without_write(tmp_path) -> None:
    class _Unexpected:
        def enrich(self, item, *, request):
            del item, request
            raise RuntimeError("PRIVATE-SENTINEL unexpected provider shape")

    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_Unexpected(),
        report_dir=tmp_path,
    ).run(_request())
    public = serialize_decision_run_result_v0(result)
    assert public["issue_code"] == "ITEM_ENRICHMENT_INVALID"
    assert "PRIVATE-SENTINEL" not in repr(public)
    assert list(tmp_path.glob("*.json")) == []


@pytest.mark.parametrize("outcome", ["prepared", "blocked"])
def test_preparer_request_mutation_is_typed_failed_without_write(
    tmp_path, outcome: str
) -> None:
    class _MutatingPreparer:
        def prepare(self, request: DecisionRunRequestV0):
            result = (
                create_run_prepared_v0(request)
                if outcome == "prepared"
                else create_run_shared_blocked_v0(
                    DecisionRunIssueCodeV0.SHARED_PREFLIGHT_UNAVAILABLE
                )
            )
            object.__setattr__(request, "created_at", object())
            return result

    result = DecisionBoardRunnerV0(
        preparer=_MutatingPreparer(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
    ).run(_request())

    assert serialize_decision_run_result_v0(result)["issue_code"] == (
        "PREPARATION_INVALID"
    )
    assert list(tmp_path.glob("*.json")) == []


def test_mutated_preparation_result_is_typed_failed_without_write(tmp_path) -> None:
    class _MutatedBlocked:
        def prepare(self, request: DecisionRunRequestV0):
            del request
            result = create_run_shared_blocked_v0(
                DecisionRunIssueCodeV0.SHARED_PREFLIGHT_UNAVAILABLE
            )
            object.__delattr__(result, "issue_codes")
            return result

    result = DecisionBoardRunnerV0(
        preparer=_MutatedBlocked(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
    ).run(_request())

    assert serialize_decision_run_result_v0(result)["issue_code"] == (
        "PREPARATION_INVALID"
    )
    assert list(tmp_path.glob("*.json")) == []


@pytest.mark.parametrize("mutation_boundary", ["before-run", "after-prepare"])
def test_request_validation_contains_metadata_runtime_error(
    tmp_path, mutation_boundary: str
) -> None:
    class _EvilMetadata(dict[str, str]):
        def items(self):
            raise RuntimeError("PRIVATE-SENTINEL metadata")

    request = _request()

    class _Preparer:
        def prepare(self, prepared_request: DecisionRunRequestV0):
            result = create_run_prepared_v0(prepared_request)
            if mutation_boundary == "after-prepare":
                object.__setattr__(prepared_request, "metadata", _EvilMetadata())
            return result

    if mutation_boundary == "before-run":
        object.__setattr__(request, "metadata", _EvilMetadata())

    result = DecisionBoardRunnerV0(
        preparer=_Preparer(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
    ).run(request)

    public = serialize_decision_run_result_v0(result)
    assert public["issue_code"] == "PREPARATION_INVALID"
    assert "PRIVATE-SENTINEL" not in repr(public)
    assert list(tmp_path.glob("*.json")) == []


@pytest.mark.parametrize(
    "mutated_field",
    ["run_id", "idempotency_key", "sealed_input_hash", "metadata_version"],
)
def test_request_validation_rejects_equal_string_subclass(
    tmp_path, mutated_field: str
) -> None:
    class _EqualString(str):
        pass

    request = _request()
    if mutated_field == "metadata_version":
        metadata = dict(request.metadata)
        metadata["policy_version"] = _EqualString(metadata["policy_version"])
        object.__setattr__(request, "metadata", metadata)
    else:
        object.__setattr__(
            request,
            mutated_field,
            _EqualString(getattr(request, mutated_field)),
        )

    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
    ).run(request)

    assert serialize_decision_run_result_v0(result)["issue_code"] == (
        "PREPARATION_INVALID"
    )
    assert list(tmp_path.glob("*.json")) == []


def test_holding_sixth_hard_sell_survives_research_cap_without_enrichment(
    tmp_path,
) -> None:
    items = tuple(
        _holding(
            index,
            hard_exit=HardExitStateV0.HARD_STOP if index == 6 else HardExitStateV0.NONE,
        )
        for index in range(1, 7)
    )
    enriched: list[str] = []

    class _HoldingEnricher:
        def enrich(self, item, *, request):
            enriched.append(item.item_id)
            return HoldingCompilerItemV0.create(
                item_id=item.item_id,
                instrument=item.instrument,
                item_state=item.item_state,
                identity_state=item.identity_state,
                hard_exit_state=item.hard_exit_state,
                broker_state=item.broker_state,
                candle_state=item.candle_state,
                rule_state=item.rule_state,
                research_state=ResearchStateV0.TIMEOUT,
                research_priority=item.research_priority,
                research_order=item.research_order,
            )

    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_HoldingEnricher(),
        report_dir=tmp_path,
    ).run(_holding_request(items))
    assert type(result) is DecisionRunPublishedV0
    assert enriched == [f"holding-SYN{index}.NAS" for index in range(1, 6)]
    rows = result.envelope["decision_payload"]["items"]
    sixth = next(
        row for row in rows if row["instrument"]["canonical_ticker"] == "SYN6.NAS"
    )
    assert sixth["status"] == "DECIDED"
    assert sixth["action"] == "SELL"


def test_selected_hard_sell_remains_sell_after_operational_timeout(tmp_path) -> None:
    item = _holding(1, hard_exit=HardExitStateV0.CONFIRMED_EXIT)

    class _Timeout:
        def enrich(self, item, *, request):
            del item, request
            raise DecisionItemEnrichmentOperationalError(ResearchStateV0.TIMEOUT)

    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_Timeout(),
        report_dir=tmp_path,
    ).run(_holding_request((item,)))
    assert type(result) is DecisionRunPublishedV0
    row = result.envelope["decision_payload"]["items"][0]
    assert (row["status"], row["action"]) == ("DECIDED", "SELL")


def test_compiler_payload_must_match_request_sealed_input_hash(
    tmp_path, monkeypatch
) -> None:
    request = _request(
        run_id="entry-wrong-compiler",
        idempotency_key="sha256:" + "a" * 64,
    )
    wrong = {
        "run_kind": "ENTRY",
        "sealed_input_hash": "sha256:" + "f" * 64,
        "items": [],
    }
    monkeypatch.setattr(
        "sab.decision_board.runner.DecisionCompilerV0.compile_entry",
        lambda *args, **kwargs: wrong,
    )
    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
    ).run(request)
    assert serialize_decision_run_result_v0(result)["issue_code"] == (
        "COMPILER_CONTRACT_INVALID"
    )
    assert list(tmp_path.glob("*.json")) == []


def test_entry_compiler_payload_rejects_foreign_instrument_before_write(
    tmp_path, monkeypatch
) -> None:
    request = _request(
        run_id="entry-foreign-compiler",
        idempotency_key="sha256:" + "b" * 64,
    )
    foreign = DecisionCompilerV0.compile_entry(
        (_numbered_entry(99),),
        sealed_input_hash=request.sealed_input_hash,
    )
    monkeypatch.setattr(
        "sab.decision_board.runner.DecisionCompilerV0.compile_entry",
        lambda *args, **kwargs: foreign,
    )

    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
    ).run(request)

    assert serialize_decision_run_result_v0(result)["issue_code"] == (
        "COMPILER_CONTRACT_INVALID"
    )
    assert list(tmp_path.glob("*.json")) == []


def test_entry_compiler_payload_may_drop_only_absent_signals_before_write(
    tmp_path, monkeypatch
) -> None:
    request = _request(
        run_id="entry-hidden-ready-compiler",
        idempotency_key="sha256:" + "d" * 64,
    )
    hidden = {
        "run_kind": "ENTRY",
        "sealed_input_hash": request.sealed_input_hash,
        "items": [],
    }
    monkeypatch.setattr(
        "sab.decision_board.runner.DecisionCompilerV0.compile_entry",
        lambda *args, **kwargs: hidden,
    )

    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
    ).run(request)

    assert serialize_decision_run_result_v0(result)["issue_code"] == (
        "COMPILER_CONTRACT_INVALID"
    )
    assert list(tmp_path.glob("*.json")) == []


def test_entry_absent_signal_still_emits_required_identity_review(tmp_path) -> None:
    item = EntryCompilerItemV0.create(
        item_id="entry-AAPL",
        instrument=_instrument(),
        item_state=ApprovalStateV0.APPROVED,
        identity_state=ApprovalStateV0.REVIEW,
        signal_state=EntrySignalStateV0.ABSENT,
        mandate_state=DependencyStateV0.CURRENT,
        price_state=DependencyStateV0.CURRENT,
        exposure_state=ExposureStateV0.PASS,
        research_state=ResearchStateV0.CLEAR,
    )

    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
    ).run(
        _request(
            run_id="entry-absent-identity-review",
            idempotency_key="sha256:" + "e" * 64,
            items=(item,),
        )
    )

    assert type(result) is DecisionRunPublishedV0
    row = result.envelope["decision_payload"]["items"][0]
    assert row["status"] == "REVIEW"
    assert row["issues"][0]["code"] == "REVIEW_IDENTITY_NOT_APPROVED"


def test_holding_compiler_payload_requires_exact_full_universe_before_write(
    tmp_path, monkeypatch
) -> None:
    items = (_holding(1), _holding(2))
    request = _holding_request(
        items,
        run_id="holding-missing-compiler",
        idempotency_key="sha256:" + "c" * 64,
    )
    partial_items = (items[0],)
    partial = DecisionCompilerV0.compile_holding(
        partial_items,
        selection=select_holding_research_v0(partial_items),
        sealed_input_hash=request.sealed_input_hash,
    )
    monkeypatch.setattr(
        "sab.decision_board.runner.DecisionCompilerV0.compile_holding",
        lambda *args, **kwargs: partial,
    )

    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_HoldingCopyEnricher(),
        report_dir=tmp_path,
    ).run(request)

    assert serialize_decision_run_result_v0(result)["issue_code"] == (
        "COMPILER_CONTRACT_INVALID"
    )
    assert list(tmp_path.glob("*.json")) == []


def test_local_writer_receives_detached_graph_without_result_alias(tmp_path) -> None:
    def mutating_writer(report: dict[str, object], *, report_dir):
        path = write_decision_board_report(report, report_dir=report_dir)
        payload = report["decision_payload"]
        assert type(payload) is dict
        payload["items"] = ["PRIVATE-SENTINEL"]
        return path

    result = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=_CopyEnricher(),
        report_dir=tmp_path,
        local_writer=mutating_writer,
    ).run(_request())
    assert type(result) is DecisionRunPublishedV0
    assert result.envelope["decision_payload"]["items"][0]["status"] == "DECIDED"
    assert "PRIVATE-SENTINEL" not in canonical_json_bytes(result.envelope).decode()
    assert (
        json.loads(result.local_path.read_text())["decision_payload"]["items"][0][
            "status"
        ]
        == "DECIDED"
    )
