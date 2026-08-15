from __future__ import annotations

import ast
import re
import shlex
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]
from sab.decision_board.compiler import (
    ApprovalStateV0,
    DependencyStateV0,
    EntryCompilerItemV0,
    EntrySignalStateV0,
    ExposureStateV0,
    ResearchStateV0,
)
from sab.decision_board.instruments import InstrumentRefV0
from sab.decision_board.results import (
    DecisionRunIssueCodeV0,
    create_decision_run_failed_v0,
)
from sab.decision_board.runner import (
    DecisionBoardRunnerV0,
    RunKindV0,
    UploadModeV0,
    create_decision_run_request_v0,
    create_run_prepared_v0,
)
from sab.decision_board.scheduler import run_decision_board_shadow_non_gating_v0

ROOT = Path(__file__).parents[1]


def _web_dependency_closure(roots: tuple[Path, ...]) -> tuple[Path, ...]:
    source_root = ROOT / "web" / "src"
    queue = deque(roots)
    found: set[Path] = set()
    imports = re.compile(r"(?:from\s+|import\s*\()[\"']([^\"']+)[\"']")
    while queue and len(found) < 512:
        path = queue.popleft()
        if path in found or not path.is_file():
            continue
        found.add(path)
        for module in imports.findall(path.read_text(encoding="utf-8")):
            if module.startswith("@/"):
                base = source_root / module[2:]
            elif module.startswith("."):
                base = path.parent / module
            else:
                continue
            candidates = (
                base,
                base.with_suffix(".ts"),
                base.with_suffix(".tsx"),
                base / "index.ts",
                base / "index.tsx",
            )
            for candidate in candidates:
                if candidate.is_file() and source_root in candidate.parents:
                    queue.append(candidate)
                    break
    return tuple(sorted(found))


_PYTHON_RUNTIME_ROOTS = (
    ROOT / "sab" / "__main__.py",
    ROOT / "sab" / "decision_board" / "cli.py",
    ROOT / "sab" / "decision_board" / "run_journal_cli.py",
    ROOT / "sab" / "decision_board" / "runner.py",
    ROOT / "sab" / "decision_board" / "scheduler.py",
    ROOT / "sab" / "report" / "decision_board.py",
    ROOT / "sab" / "report" / "supabase_storage.py",
)


def _python_dependency_closure(
    roots: tuple[Path, ...], *, extra_files: tuple[Path, ...] = ()
) -> tuple[Path, ...]:
    sab_root = ROOT / "sab"
    module_files = {
        path.relative_to(ROOT).with_suffix("").parts: path
        for path in sab_root.rglob("*.py")
    }
    for path in extra_files:
        module_files[("sab", path.stem)] = path
    package_files = {
        parts[:-1]: path
        for parts, path in module_files.items()
        if parts[-1] == "__init__"
    }
    queue = deque(roots)
    found: set[Path] = set()
    while queue and len(found) < 1_024:
        path = queue.popleft()
        if path in found or not path.is_file():
            continue
        found.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        current = (
            path.relative_to(ROOT).with_suffix("").parts
            if path.is_relative_to(ROOT)
            else ("sab", path.stem)
        )
        package = current[:-1]
        for node in ast.walk(tree):
            names: list[tuple[str, ...]] = []
            if isinstance(node, ast.Import):
                names.extend(tuple(alias.name.split(".")) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = tuple((node.module or "").split(".")) if node.module else ()
                if node.level:
                    base = package[: len(package) - node.level + 1] + base
                names.append(base)
                names.extend(
                    base + tuple(alias.name.split(".")) for alias in node.names
                )
            for name in names:
                candidate = module_files.get(name) or package_files.get(name)
                if candidate is not None and (
                    sab_root in candidate.parents or candidate in extra_files
                ):
                    queue.append(candidate)
    return tuple(sorted(found))


PYTHON_RUNTIME = _python_dependency_closure(_PYTHON_RUNTIME_ROOTS)
_WEB_RUNTIME_ROOTS = tuple(
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
WEB_RUNTIME = _web_dependency_closure(_WEB_RUNTIME_ROOTS)
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
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                part = _constant_text(value.value, names)
            else:
                part = _constant_text(value, names)
            if part is None:
                return None
            parts.append(part)
        return "".join(parts)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and len(node.args) == 1
    ):
        separator = _constant_text(node.func.value, names)
        values = node.args[0]
        if separator is not None and isinstance(values, (ast.List, ast.Tuple)):
            joined_parts = [_constant_text(item, names) for item in values.elts]
            if all(part is not None for part in joined_parts):
                return separator.join(part for part in joined_parts if part is not None)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    ):
        template = _constant_text(node.func.value, names)
        arguments = [_constant_text(argument, names) for argument in node.args]
        if template is not None and all(argument is not None for argument in arguments):
            try:
                return template.format(
                    *(argument for argument in arguments if argument is not None)
                )
            except IndexError, KeyError, ValueError:
                return None
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

    assignments = [
        node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    for _pass in range(len(assignments) + 1):
        changed = False
        for assignment in assignments:
            targets = (
                assignment.targets
                if isinstance(assignment, ast.Assign)
                else [assignment.target]
            )
            value = assignment.value
            if value is None:
                continue
            constant = _constant_text(value, strings)
            dangerous = _dangerous_callable(value, strings)
            for target in targets:
                if isinstance(target, ast.Name):
                    if constant is not None:
                        changed |= strings.get(target.id) != constant
                        strings[target.id] = constant
                    if dangerous is None and isinstance(value, ast.Name):
                        dangerous = callables.get(value.id)
                    if dangerous is not None:
                        changed |= callables.get(target.id) != dangerous
                        callables[target.id] = dangerous
        if not changed:
            break

    for import_node in ast.walk(tree):
        if isinstance(import_node, ast.Import):
            for alias in import_node.names:
                if set(alias.name.casefold().split(".")) & FORBIDDEN_IMPORT_PARTS:
                    violations.append(f"{relative}:import")
        elif isinstance(import_node, ast.ImportFrom):
            parts = set((import_node.module or "").casefold().split("."))
            for alias in import_node.names:
                imported = alias.name.casefold()
                if parts & FORBIDDEN_IMPORT_PARTS or imported in FORBIDDEN_IMPORT_PARTS:
                    violations.append(f"{relative}:import")
                if imported in FORBIDDEN_CALL_SYMBOLS:
                    callables[alias.asname or alias.name] = imported

    for walk_node in ast.walk(tree):
        if isinstance(walk_node, ast.Call):
            dangerous = _dangerous_callable(walk_node.func, strings)
            if dangerous is None and isinstance(walk_node.func, ast.Name):
                dangerous = callables.get(walk_node.func.id)
            if dangerous is not None:
                violations.append(f"{relative}:call:{dangerous}")
            if isinstance(walk_node.func, ast.Attribute) and walk_node.func.attr in {
                "delete",
                "patch",
                "post",
                "put",
            }:
                for argument in (
                    *walk_node.args,
                    *(keyword.value for keyword in walk_node.keywords),
                ):
                    endpoint = _constant_text(argument, strings)
                    if endpoint is not None and broker_write_path.search(endpoint):
                        violations.append(f"{relative}:endpoint")
        elif isinstance(walk_node, (ast.Constant, ast.BinOp, ast.Name)):
            text_value = _constant_text(walk_node, strings)
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


def test_python_dependency_closure_reaches_new_transitive_local_module(
    tmp_path: Path,
) -> None:
    sab = tmp_path / "sab"
    sab.mkdir()
    root = sab / "entry.py"
    transitive = sab / "transitive.py"
    root.write_text("from sab import transitive\n", encoding="utf-8")
    transitive.write_text("client.create_order()\n", encoding="utf-8")

    closure = _python_dependency_closure((root,), extra_files=(root, transitive))

    assert transitive in closure
    assert _python_capability_violations(transitive)


def test_capability_detector_rejects_alias_getattr_and_split_endpoint(
    tmp_path: Path,
) -> None:
    cases = {
        "alias.py": "order_fn = client.create_order\norder_fn()\n",
        "getattr.py": 'getattr(client, "create_" + "order")()\n',
        "endpoint.py": 'path = "/ord" + "ers"\nsession.post(path)\n',
        "alias-chain.py": "a = client.create_order\nb = a\nb()\n",
        "getattr-join.py": ('getattr(client, "_".join(("create", "order")))()\n'),
        "endpoint-join.py": ('path = "".join(("/ord", "ers"))\nsession.post(path)\n'),
        "f-string.py": 'verb = "order"\ngetattr(client, f"create_{verb}")()\n',
        "format.py": 'getattr(client, "create_{}".format("order"))()\n',
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


def _resolve_shell_assignments(command: str) -> str:
    variables: dict[str, str] = {}
    for line in command.splitlines():
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)=(?:[\"']?)([^\s;\"']+)", line)
        if match:
            variables[match.group(1)] = match.group(2)
    normalized = command
    for name, value in variables.items():
        normalized = normalized.replace(f"${{{name}}}", value).replace(
            f"${name}", value
        )
    return normalized


def _production_workflow_invocation(command: str) -> bool:
    normalized = _resolve_shell_assignments(command)
    normalized = normalized.replace('"', "").replace("'", "")
    normalized = re.sub(r"\s*\+\s*", "", normalized)
    return (
        re.search(
            r"(?:\bsab\s+decision-(?:board|\$|\$\{)|"
            r"getattr\([^\n)]*decision_board|\bdecision_board\s*\(|"
            r"decision-board-journal|"
            r"sab-decision-board-shadow-wrapper|run_decision_board_shadow|"
            r"upload_decision_board_report)",
            normalized,
            re.I,
        )
        is not None
    )


def _repo_command_closure(command: str) -> tuple[str, ...]:
    """Bounded expansion of invoked local scripts and Just recipes."""

    found: list[str] = []
    queue = deque([command])
    seen: set[str] = set()
    just_source = (ROOT / "justfile").read_text(encoding="utf-8")
    recipes: dict[str, str] = {}
    current: str | None = None
    for line in just_source.splitlines():
        header = re.match(r"^([a-zA-Z0-9_-]+)(?:\s+[^:]*)?:\s*$", line)
        if header:
            current = header.group(1)
            recipes[current] = ""
        elif current is not None and line.startswith(("  ", "\t")):
            recipes[current] += line.strip() + "\n"
        elif line and not line.startswith("#"):
            current = None
    while queue and len(seen) < 64:
        value = queue.popleft()
        if value in seen:
            continue
        seen.add(value)
        found.append(value)
        resolved = _resolve_shell_assignments(value)
        try:
            tokens = shlex.split(resolved, comments=True)
        except ValueError:
            tokens = value.split()
        for index, token in enumerate(tokens):
            if token == "just" and index + 1 < len(tokens):
                recipe = tokens[index + 1]
                if recipe in recipes:
                    queue.append(recipes[recipe])
            candidate = ROOT / token
            if (
                token.startswith(("scripts/", "./scripts/"))
                and candidate.is_file()
                and candidate.stat().st_size <= 1_048_576
            ):
                queue.append(candidate.read_text(encoding="utf-8"))
    return tuple(found)


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
                if any(
                    _production_workflow_invocation(candidate)
                    for candidate in _repo_command_closure(command)
                ):
                    violations.append(f"{path.name}:{step.get('name', 'unnamed')}")
                if _is_exact_offline_ci_command(command):
                    recorded_ci_steps.append(f"{path.name}:{step.get('name', '')}")
    assert violations == []
    assert recorded_ci_steps == ["ci.yml:Decision Board offline verification"]


def test_workflow_detector_rejects_dynamic_split_and_echo_false_positive() -> None:
    assert _production_workflow_invocation("uv run python -m sab decision-$MODE")
    assert _production_workflow_invocation('uv run python -m sab decision-"board"')
    assert _production_workflow_invocation(
        "MODE=board\nuv run python -m sab decision-$MODE"
    )
    assert _production_workflow_invocation(
        'python -c \'import sab; getattr(sab, "decision_" + "board")\''
    )
    assert not _is_exact_offline_ci_command(
        "echo tests/test_decision_board_verification.py"
    )


def test_workflow_detector_follows_just_recipes_and_local_scripts(
    tmp_path: Path,
) -> None:
    closure = _repo_command_closure("just decision-board-claim-live-compare")
    assert any("compare_decision_board_claim_live.py" in value for value in closure)
    script = ROOT / "scripts" / "launchd" / "sab-decision-board-shadow-wrapper.sh"
    command = f'SCRIPT={script.relative_to(ROOT)}\nuv run python "$SCRIPT"'
    expanded = _repo_command_closure(command)
    assert any("decision-board-journal-run" in value for value in expanded)


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


class _PoisonedShadowRuntime:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.capability_accesses: list[str] = []

    def __getattr__(self, name: str):
        if name in FORBIDDEN_CALL_SYMBOLS:
            self.capability_accesses.append(name)
            raise AssertionError(f"forbidden capability lookup: {name}")
        raise AttributeError(name)

    def __call__(self, _upload_mode: object):
        if self.mode == "failure":
            raise RuntimeError("synthetic shadow failure")
        if self.mode == "timeout":
            raise TimeoutError("synthetic shadow timeout")
        return create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.INTERNAL_ERROR
        )


class _PoisonedCollaborator:
    def __init__(self, role: str, *, fail: bool = False) -> None:
        self.role = role
        self.fail = fail
        self.capability_accesses: list[str] = []
        self.method_calls: list[str] = []

    def __getattr__(self, name: str):
        if name in FORBIDDEN_CALL_SYMBOLS:
            self.capability_accesses.append(name)
            raise AssertionError(f"forbidden {self.role} capability lookup: {name}")
        raise AttributeError(name)

    def prepare(self, _request: object):
        self.method_calls.append("prepare")
        if self.fail:
            raise RuntimeError("prepared failure")
        return create_run_prepared_v0(_request)  # type: ignore[arg-type]

    def enrich(self, _item: object, *, request: object):
        self.method_calls.append("enrich")
        del request
        if self.fail:
            raise RuntimeError("enrichment failure")
        item = _item
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
            research_state=item.research_state,
            evidence=item.evidence,
        )

    def upload(self, *, local_path: Path, storage_key: str):
        self.method_calls.append("upload")
        del local_path
        if self.fail:
            raise RuntimeError("upload failure")
        return storage_key


def _runner_probe_request():
    instrument = InstrumentRefV0(
        market="US",
        canonical_ticker="AUR.NAS",
        exchange="NASDAQ",
        company_name="Aurora Systems",
        identity_source="probe-directory",
        identity_version="probe-v0",
    )
    item = EntryCompilerItemV0.create(
        item_id="entry-AUR.NAS",
        instrument=instrument,
        item_state=ApprovalStateV0.APPROVED,
        identity_state=ApprovalStateV0.APPROVED,
        signal_state=EntrySignalStateV0.READY_ENTER,
        mandate_state=DependencyStateV0.CURRENT,
        price_state=DependencyStateV0.CURRENT,
        exposure_state=ExposureStateV0.PASS,
        research_state=ResearchStateV0.COVERAGE_GAP,
    )
    return create_decision_run_request_v0(
        run_kind=RunKindV0.ENTRY,
        run_id="entry-capability-probe",
        idempotency_key="sha256:" + "1" * 64,
        created_at=datetime(2026, 8, 13, tzinfo=UTC),
        sealed_input_hash="sha256:" + "2" * 64,
        items=(item,),
        selection=None,
        upload_mode=UploadModeV0.OPTIONAL,
        metadata={
            "policy_version": "probe-v0",
            "researcher_version": "probe-v0",
            "verifier_version": "probe-v0",
        },
    )


def test_actual_runner_collaborators_never_probe_forbidden_capabilities(
    tmp_path: Path,
) -> None:
    preparer = _PoisonedCollaborator("preparer")
    enricher = _PoisonedCollaborator("enricher")
    uploader = _PoisonedCollaborator("uploader")
    runner = DecisionBoardRunnerV0(
        preparer=preparer,
        enricher=enricher,
        uploader=uploader,
        report_dir=tmp_path,
    )

    runner.run(_runner_probe_request())

    assert preparer.capability_accesses == []
    assert enricher.capability_accesses == []
    assert uploader.capability_accesses == []
    assert preparer.method_calls == ["prepare"]
    assert enricher.method_calls == ["enrich"]
    assert uploader.method_calls == ["upload"]


@pytest.mark.parametrize("mode", ["failure", "timeout", "failed-result"])
def test_shadow_failure_is_identity_equal_non_gating_and_capability_free(
    mode: str,
) -> None:
    existing = _ExistingPipelineResult()
    before = bytes(existing.payload)

    runtime = _PoisonedShadowRuntime(mode)

    returned, summary = run_decision_board_shadow_non_gating_v0(existing, runtime)

    assert returned is existing
    assert returned.payload is existing.payload
    assert bytes(returned.payload) == before
    assert summary.to_public_dict() == {"status": "FAILED", "exit_code": 2}
    assert existing.capability_accesses == []
    assert runtime.capability_accesses == []


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
