from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]
from sab.decision_board.results import (
    DecisionRunIssueCodeV0,
    create_decision_run_failed_v0,
)
from sab.decision_board.scheduler import run_decision_board_shadow_non_gating_v0

ROOT = Path(__file__).parents[1]
PYTHON_RUNTIME = (
    *sorted((ROOT / "sab" / "decision_board").glob("*.py")),
    *sorted((ROOT / "sab" / "research").glob("*.py")),
    ROOT / "sab" / "report" / "decision_board.py",
    ROOT / "sab" / "report" / "supabase_storage.py",
)
WEB_RUNTIME = tuple(
    dict.fromkeys(
        (
            *sorted(
                path
                for path in (ROOT / "web" / "src" / "app" / "api" / "reports").rglob(
                    "*.ts"
                )
                if "__tests__" not in path.parts
            ),
            ROOT / "web" / "src" / "app" / "(console)" / "reports" / "page.tsx",
            ROOT / "web" / "src" / "components" / "reports-client.tsx",
            *sorted(
                path
                for path in (ROOT / "web" / "src" / "components" / "reports").rglob(
                    "*.tsx"
                )
                if "__tests__" not in path.parts
            ),
            ROOT / "web" / "src" / "lib" / "decision-board-json.ts",
            ROOT / "web" / "src" / "lib" / "decision-board-journal.server.ts",
            ROOT / "web" / "src" / "lib" / "decision-board-schema.ts",
            ROOT / "web" / "src" / "lib" / "report-key.ts",
            ROOT / "web" / "src" / "lib" / "reports-data.ts",
            ROOT / "web" / "src" / "lib" / "supabase" / "reports.ts",
        )
    )
)
LOCAL_RUNTIME = (
    ROOT / "scripts" / "launchd" / "sab-decision-board-shadow-wrapper.sh",
    ROOT
    / "scripts"
    / "launchd"
    / "com.mochafreddo.sab.decision-board.entry-shadow.plist.template",
    ROOT
    / "scripts"
    / "launchd"
    / "com.mochafreddo.sab.decision-board.holding-shadow.plist.template",
)
FORBIDDEN_CALL_SYMBOLS = {
    "amend_order",
    "cancel_conditional_order",
    "cancel_order",
    "create_conditional_order",
    "create_order",
    "modify_order",
    "notify",
    "place_order",
    "post_message",
    "send_notification",
    "send_order",
    "send_slack",
    "send_telegram",
    "submit_order",
}
FORBIDDEN_IMPORT_PARTS = {
    "broker_write",
    "notification",
    "notifications",
    "orders",
    "slack",
    "telegram",
    "toss_order",
}
FORBIDDEN_WEB_SYMBOLS = {
    "amendOrder",
    "cancelConditionalOrder",
    "cancelOrder",
    "createConditionalOrder",
    "createOrder",
    "modifyOrder",
    "notify",
    "placeOrder",
    "postMessage",
    "sendNotification",
    "sendOrder",
    "sendSlack",
    "sendTelegram",
    "submitOrder",
}


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def test_complete_decision_board_runtime_has_no_order_or_notification_capability() -> (
    None
):
    violations: list[str] = []
    broker_write_path = re.compile(r"/(?:orders?|conditional-orders?)(?:/|$)", re.I)
    for path in PYTHON_RUNTIME:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                symbol = _call_name(node.func)
                if symbol in FORBIDDEN_CALL_SYMBOLS:
                    violations.append(f"{path.relative_to(ROOT)}:call:{symbol}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = set(alias.name.casefold().split("."))
                    if parts & FORBIDDEN_IMPORT_PARTS:
                        violations.append(f"{path.relative_to(ROOT)}:import")
            elif isinstance(node, ast.ImportFrom):
                parts = set((node.module or "").casefold().split("."))
                imported = {alias.name.casefold() for alias in node.names}
                if parts & FORBIDDEN_IMPORT_PARTS or imported & FORBIDDEN_IMPORT_PARTS:
                    violations.append(f"{path.relative_to(ROOT)}:import")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.casefold()
                if value in FORBIDDEN_CALL_SYMBOLS:
                    violations.append(f"{path.relative_to(ROOT)}:dynamic-symbol")
                elif broker_write_path.search(value) or (
                    "toss" in value and value.startswith(("http://", "https://"))
                ):
                    violations.append(f"{path.relative_to(ROOT)}:endpoint")

    import_pattern = re.compile(
        r"(?:from\s+|import\s*\()[\"']([^\"']+)[\"']", re.MULTILINE
    )
    for path in WEB_RUNTIME:
        source = path.read_text(encoding="utf-8")
        for module in import_pattern.findall(source):
            if (
                set(module.casefold().replace("@/", "").split("/"))
                & FORBIDDEN_IMPORT_PARTS
            ):
                violations.append(f"{path.relative_to(ROOT)}:import")
        for symbol in FORBIDDEN_WEB_SYMBOLS:
            if re.search(rf"\b{re.escape(symbol)}\s*\(", source):
                violations.append(f"{path.relative_to(ROOT)}:call:{symbol}")
        if re.search(r"/(?:orders?|conditional-orders?)(?:/|[\"'`])", source, re.I):
            violations.append(f"{path.relative_to(ROOT)}:endpoint")

    shell_call = re.compile(
        r"(?:^|[;&|]\s*)(?:[A-Za-z0-9_./-]+/)?"
        r"(?:create-order|modify-order|cancel-order|send-telegram|send-slack|notify)"
        r"(?:\s|$)",
        re.MULTILINE,
    )
    for path in LOCAL_RUNTIME:
        source = path.read_text(encoding="utf-8")
        if shell_call.search(source):
            violations.append(f"{path.relative_to(ROOT)}:command")

    assert violations == []


def test_github_workflows_keep_decision_board_local_and_ci_test_only() -> None:
    production_invocation = re.compile(
        r"(?:\bsab\s+decision-board(?:\s|$)|decision-board-journal|"
        r"sab-decision-board-shadow-wrapper|run_decision_board_shadow|"
        r"upload_decision_board_report)",
        re.I,
    )
    violations: list[str] = []
    recorded_ci_steps: list[str] = []
    workflow_paths = sorted(
        (
            *(ROOT / ".github" / "workflows").glob("*.yml"),
            *(ROOT / ".github" / "workflows").glob("*.yaml"),
        )
    )
    for path in workflow_paths:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert type(workflow) is dict
        for job in workflow.get("jobs", {}).values():
            for step in job.get("steps", []):
                command = step.get("run")
                if type(command) is not str:
                    continue
                if production_invocation.search(command):
                    violations.append(f"{path.name}:{step.get('name', 'unnamed')}")
                if "tests/test_decision_board_verification.py" in command:
                    recorded_ci_steps.append(f"{path.name}:{step.get('name', '')}")
    assert violations == []
    assert recorded_ci_steps == ["ci.yml:Decision Board offline verification"]


class _ExistingPipelineResult:
    def __init__(self) -> None:
        self.payload = b"existing-pipeline-result\x00unchanged"
        self.capability_accesses: list[str] = []

    def send_telegram(self, *_args: object, **_kwargs: object) -> None:
        self.capability_accesses.append("send_telegram")
        raise AssertionError("notification capability was accessed")

    def send_slack(self, *_args: object, **_kwargs: object) -> None:
        self.capability_accesses.append("send_slack")
        raise AssertionError("notification capability was accessed")

    def create_order(self, *_args: object, **_kwargs: object) -> None:
        self.capability_accesses.append("create_order")
        raise AssertionError("order capability was accessed")

    def modify_order(self, *_args: object, **_kwargs: object) -> None:
        self.capability_accesses.append("modify_order")
        raise AssertionError("order capability was accessed")

    def cancel_order(self, *_args: object, **_kwargs: object) -> None:
        self.capability_accesses.append("cancel_order")
        raise AssertionError("order capability was accessed")


@pytest.mark.parametrize("mode", ["failure", "timeout", "failed-result"])
def test_shadow_failure_is_identity_equal_non_gating_and_capability_free(
    mode: str,
) -> None:
    existing = _ExistingPipelineResult()
    before = bytes(existing.payload)

    def run_once(_upload_mode: object):
        if mode == "failure":
            raise RuntimeError("synthetic shadow failure")
        if mode == "timeout":
            raise TimeoutError("synthetic shadow timeout")
        return create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.INTERNAL_ERROR
        )

    returned, summary = run_decision_board_shadow_non_gating_v0(existing, run_once)

    assert returned is existing
    assert returned.payload is existing.payload
    assert bytes(returned.payload) == before
    assert summary.to_public_dict() == {"status": "FAILED", "exit_code": 2}
    assert existing.capability_accesses == []


def test_local_shadow_templates_remain_disabled_and_unreferenced_by_workflows() -> None:
    templates = LOCAL_RUNTIME[1:]
    for path in templates:
        source = path.read_text(encoding="utf-8")
        assert "<key>Disabled</key>" in source
        assert "<true/>" in source
        assert "StartCalendarInterval" not in source
    workflow_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(
            (
                *(ROOT / ".github" / "workflows").glob("*.yml"),
                *(ROOT / ".github" / "workflows").glob("*.yaml"),
            )
        )
    )
    for path in LOCAL_RUNTIME:
        assert path.name not in workflow_text
