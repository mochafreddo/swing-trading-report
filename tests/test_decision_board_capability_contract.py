from __future__ import annotations

import ast
import re
import shlex
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
    ROOT / "sab" / "__main__.py",
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
                for path in (ROOT / "web" / "src" / "components" / "reports").rglob("*")
                if path.suffix in {".ts", ".tsx"} and "__tests__" not in path.parts
            ),
            ROOT / "web" / "src" / "lib" / "decision-board-json.ts",
            ROOT / "web" / "src" / "lib" / "decision-board-journal.server.ts",
            ROOT / "web" / "src" / "lib" / "decision-board-schema.ts",
            ROOT / "web" / "src" / "lib" / "report-key.ts",
            ROOT / "web" / "src" / "lib" / "reports-data.ts",
            ROOT / "web" / "src" / "lib" / "reports-response.ts",
            ROOT / "web" / "src" / "lib" / "supabase-admin.ts",
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


def _constant_text(node: ast.expr, names: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return names.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _constant_text(node.left, names)
        right = _constant_text(node.right, names)
        if left is not None and right is not None:
            return left + right
    return None


def _dangerous_callable(node: ast.expr, strings: dict[str, str]) -> str | None:
    name = _call_name(node)
    if name in FORBIDDEN_CALL_SYMBOLS:
        return name
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
    ):
        dynamic = _constant_text(node.args[1], strings)
        if dynamic in FORBIDDEN_CALL_SYMBOLS:
            return dynamic
    return None


def _python_capability_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    relative = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    violations: list[str] = []
    strings: dict[str, str] = {}
    callables: dict[str, str] = {}
    broker_write_path = re.compile(r"/(?:orders?|conditional-orders?)(?:/|$)", re.I)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is None:
                continue
            constant = _constant_text(value, strings)
            dangerous = _dangerous_callable(value, strings)
            for target in targets:
                if isinstance(target, ast.Name):
                    if constant is not None:
                        strings[target.id] = constant
                    if dangerous is not None:
                        callables[target.id] = dangerous
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if set(alias.name.casefold().split(".")) & FORBIDDEN_IMPORT_PARTS:
                    violations.append(f"{relative}:import")
        elif isinstance(node, ast.ImportFrom):
            parts = set((node.module or "").casefold().split("."))
            for alias in node.names:
                imported = alias.name.casefold()
                if parts & FORBIDDEN_IMPORT_PARTS or imported in FORBIDDEN_IMPORT_PARTS:
                    violations.append(f"{relative}:import")
                if imported in FORBIDDEN_CALL_SYMBOLS:
                    callables[alias.asname or alias.name] = imported

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dangerous = _dangerous_callable(node.func, strings)
            if dangerous is None and isinstance(node.func, ast.Name):
                dangerous = callables.get(node.func.id)
            if dangerous is not None:
                violations.append(f"{relative}:call:{dangerous}")
            if isinstance(node.func, ast.Attribute) and node.func.attr in {
                "delete",
                "patch",
                "post",
                "put",
            }:
                for argument in (
                    *node.args,
                    *(keyword.value for keyword in node.keywords),
                ):
                    endpoint = _constant_text(argument, strings)
                    if endpoint is not None and broker_write_path.search(endpoint):
                        violations.append(f"{relative}:endpoint")
        elif isinstance(node, (ast.Constant, ast.BinOp, ast.Name)):
            text_value = _constant_text(node, strings)
            if text_value is None:
                continue
            folded = text_value.casefold()
            if folded in FORBIDDEN_CALL_SYMBOLS:
                violations.append(f"{relative}:dynamic-symbol")
            elif broker_write_path.search(folded) or (
                "toss" in folded and folded.startswith(("http://", "https://"))
            ):
                violations.append(f"{relative}:endpoint")
    return violations


def test_complete_decision_board_runtime_has_no_order_or_notification_capability() -> (
    None
):
    violations: list[str] = []
    for path in PYTHON_RUNTIME:
        violations.extend(_python_capability_violations(path))

    import_pattern = re.compile(
        r"(?:from\s+|import\s*\()[\"']([^\"']+)[\"']", re.MULTILINE
    )
    for path in WEB_RUNTIME:
        source = path.read_text(encoding="utf-8")
        folded_source = re.sub(r"[\"'`]\s*\+\s*[\"'`]", "", source)
        for module in import_pattern.findall(source):
            if (
                set(module.casefold().replace("@/", "").split("/"))
                & FORBIDDEN_IMPORT_PARTS
            ):
                violations.append(f"{path.relative_to(ROOT)}:import")
        for symbol in FORBIDDEN_WEB_SYMBOLS:
            if re.search(rf"\b{re.escape(symbol)}\s*\(", source):
                violations.append(f"{path.relative_to(ROOT)}:call:{symbol}")
        if re.search(
            r"/(?:orders?|conditional-orders?)(?:/|[\"'`])", folded_source, re.I
        ):
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


def test_capability_detector_rejects_alias_getattr_and_split_endpoint(
    tmp_path: Path,
) -> None:
    cases = {
        "alias.py": "order_fn = client.create_order\norder_fn()\n",
        "getattr.py": 'getattr(client, "create_" + "order")()\n',
        "endpoint.py": 'path = "/ord" + "ers"\nsession.post(path)\n',
    }
    for name, source in cases.items():
        path = tmp_path / name
        path.write_text(source, encoding="utf-8")
        assert _python_capability_violations(path), name


_OFFLINE_CI_ARGV = (
    "uv",
    "run",
    "python",
    "-m",
    "pytest",
    "-q",
    "tests/test_decision_board_verification.py",
    "tests/test_decision_board_privacy_integration.py",
    "tests/test_decision_board_capability_contract.py",
)


def _is_exact_offline_ci_command(command: str) -> bool:
    try:
        return tuple(shlex.split(command)) == _OFFLINE_CI_ARGV
    except ValueError:
        return False


def _production_workflow_invocation(command: str) -> bool:
    normalized = command.replace('"', "").replace("'", "")
    return (
        re.search(
            r"(?:\bsab\s+decision-(?:board|\$|\$\{)|decision-board-journal|"
            r"sab-decision-board-shadow-wrapper|run_decision_board_shadow|"
            r"upload_decision_board_report)",
            normalized,
            re.I,
        )
        is not None
    )


def test_github_workflows_keep_decision_board_local_and_ci_test_only() -> None:
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
                if _production_workflow_invocation(command):
                    violations.append(f"{path.name}:{step.get('name', 'unnamed')}")
                if _is_exact_offline_ci_command(command):
                    recorded_ci_steps.append(f"{path.name}:{step.get('name', '')}")
    assert violations == []
    assert recorded_ci_steps == ["ci.yml:Decision Board offline verification"]


def test_workflow_detector_rejects_dynamic_split_and_echo_false_positive() -> None:
    assert _production_workflow_invocation("uv run python -m sab decision-$MODE")
    assert _production_workflow_invocation('uv run python -m sab decision-"board"')
    assert not _is_exact_offline_ci_command(
        "echo tests/test_decision_board_verification.py"
    )


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
