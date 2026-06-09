from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

ARCHIVE_DOC_DIRS = (
    Path("docs/adr"),
    Path("docs/reviews"),
)

ARTIFACT_DOC_GLOBS = ("docs/governance/*.json",)

DOC_STATE_SECTION_DOCS = (
    Path("README.md"),
    Path("docs/README.md"),
    Path("docs/overview.md"),
    Path("docs/local-development.md"),
    Path("docs/configuration.md"),
    Path("docs/api.md"),
    Path("docs/deployment.md"),
    Path("docs/operations.md"),
    Path("docs/troubleshooting.md"),
    Path("docs/contributing.md"),
    Path("docs/runbook.md"),
    Path("docs/ARCHITECTURE.md"),
    Path("docs/STRATEGY.md"),
    Path("docs/PRD.md"),
    Path("docs/spec-v1.1.md"),
    Path("docs/spec-v1.3.md"),
    Path("docs/holdings-schema.md"),
    Path("docs/kis-setup.md"),
    Path("docs/holdings-ticker-lookup.md"),
    Path("docs/holdings-add-buy.md"),
    Path("docs/config-reference.md"),
    Path("docs/governance/main-branch-protection.md"),
    Path("docs/codex-systematic-equities-team.md"),
)

INDEX_DOCS = (
    Path("README.md"),
    Path("docs/README.md"),
    Path("docs/adr/README.md"),
    Path("docs/reviews/README.md"),
)

STATUS_PATTERN = re.compile(
    r"^상태:\s*(Accepted|Backlog|Archive|Superseded|채택|대체됨)",
    re.MULTILINE,
)
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _read(path: Path) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _iter_status_docs() -> list[Path]:
    docs = [Path("README.md")]
    docs.extend(
        sorted(
            path.relative_to(REPO_ROOT) for path in (REPO_ROOT / "docs").rglob("*.md")
        )
    )
    return [
        path
        for path in docs
        if not (
            len(path.parts) >= 3
            and path.parts[:2] == ("docs", "reviews")
            and path.name != "README.md"
        )
    ]


def _resolve_local_links(doc_path: Path) -> list[Path]:
    resolved: list[Path] = []
    for match in MARKDOWN_LINK_PATTERN.finditer(_read(doc_path)):
        target = match.group(1).strip()
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        target = target.split("#", 1)[0]
        resolved.append((doc_path.parent / target).resolve())
    return resolved


def test_non_archive_docs_declare_allowed_status_meta() -> None:
    for path in _iter_status_docs():
        text = _read(path)
        header_window = "\n".join(text.splitlines()[:6])
        assert STATUS_PATTERN.search(header_window), f"{path} missing allowed 상태 meta"


def test_operational_docs_include_document_state_sections() -> None:
    required_headings = (
        "## 문서 상태",
        "### 현재 제공",
        "### 실험",
        "### 백로그",
        "### 폐기 후보",
    )
    for path in DOC_STATE_SECTION_DOCS:
        text = _read(path)
        for heading in required_headings:
            assert heading in text, f"{path} missing heading: {heading}"


def test_archive_collections_are_exempt_from_document_state_section_contract() -> None:
    required_paths = set(DOC_STATE_SECTION_DOCS)
    archive_docs = [
        path.relative_to(REPO_ROOT)
        for archive_dir in ARCHIVE_DOC_DIRS
        for path in (REPO_ROOT / archive_dir).rglob("*.md")
    ]
    assert archive_docs, f"no archive docs found under {ARCHIVE_DOC_DIRS}"
    for rel_path in archive_docs:
        assert rel_path not in required_paths, (
            f"{rel_path} should stay outside operational 문서 상태 section contract"
        )


def test_docs_index_declares_archive_and_artifact_categories() -> None:
    text = _read(Path("docs/README.md"))
    for heading in (
        "## 현재 운영 기준",
        "## 설계 기록",
        "## backlog spec / roadmap",
        "## archive",
        "## artifact",
    ):
        assert heading in text


def test_docs_index_lists_local_scheduler_plan_as_accepted_design() -> None:
    text = _read(Path("docs/README.md"))
    design_section = text.split("## 설계 기록", 1)[1].split("## backlog", 1)[0]
    backlog_section = text.split("## backlog spec / roadmap", 1)[1].split(
        "## archive", 1
    )[0]

    assert "[로컬 Docker scheduler 전환 계획](local-docker-scheduler-plan.md)" in (
        design_section
    )
    assert "local-docker-scheduler-plan.md" not in backlog_section


def test_architecture_links_local_scheduler_adr() -> None:
    text = _read(Path("docs/ARCHITECTURE.md"))

    assert "docs/adr/ADR-0012-local-docker-scheduled-runs.md" in text


def test_operations_keeps_scheduled_ai_brief_guidance_in_scheduled_section() -> None:
    text = _read(Path("docs/operations.md"))
    daily_section = text.split("## Daily Checklist", 1)[1].split(
        "## Weekly Checklist", 1
    )[0]
    scheduled_section = text.split("## Scheduled AI Brief", 1)[1].split(
        "## GitHub Actions", 1
    )[0]

    assert "scheduled 기본값" not in daily_section
    assert "AI_BRIEF_SOURCE_PROVIDER_US" in scheduled_section
    assert "scheduled 기본값" in scheduled_section


def test_index_docs_link_existing_files() -> None:
    links = [
        (doc_path, resolved)
        for doc_path in INDEX_DOCS
        for resolved in _resolve_local_links(doc_path)
    ]
    assert links, "no local links found across index docs"
    for doc_path, resolved in links:
        assert resolved.exists(), f"{doc_path} links missing file: {resolved}"


def test_artifact_globs_are_centrally_declared() -> None:
    for pattern in ARTIFACT_DOC_GLOBS:
        matches = list(REPO_ROOT.glob(pattern))
        assert matches, f"artifact glob has no matches: {pattern}"


def test_strategy_docs_include_swing_logic_improvement_contracts() -> None:
    strategy_text = _read(Path("docs/STRATEGY.md"))
    config_reference_text = _read(Path("docs/config-reference.md"))
    configuration_text = _read(Path("docs/configuration.md"))
    safety_design_text = _read(
        Path("docs/superpowers/specs/2026-06-07-swing-operational-safety-design.md")
    )

    assert "market_regime_unavailable_policy" in strategy_text
    assert "quality_state" in strategy_text
    assert "risk_alignment" in strategy_text
    assert "MARKET_REGIME_UNAVAILABLE_POLICY" in config_reference_text
    assert "entry_check.fatal_missing_price_ratio" in strategy_text
    assert "ENTRY_FATAL_MISSING_PRICE_RATIO" in config_reference_text
    assert "entry_check.fatal_missing_price_ratio" in config_reference_text
    assert (
        "| `ENTRY_FATAL_MISSING_PRICE_RATIO` | `sab entry` | "
        "`entry_check.fatal_missing_price_ratio`, 0.0-1.0, active default 0.0; "
        "env override only when no YAML config is loaded"
    ) in config_reference_text
    assert (
        "| `KIS_MIN_INTERVAL_MS` | no | `config.yaml` `kis.min_interval_ms` | `200`"
        in configuration_text
    )
    assert (
        "Scheduler runtime env override only works when the selected YAML config omits `kis.base_url`."
        in configuration_text
    )
    assert (
        "omitted operational safety keys inherit the active safety defaults"
        in configuration_text
    )
    assert "tests/test_config_validation_layers.py" in configuration_text
    assert "tests/test_runtime_config_contract.py" in configuration_text
    assert "Loaded YAML configs with omitted custom safety keys inherit" in (
        safety_design_text
    )
    assert "code-level compatibility default `warn_continue`" not in safety_design_text
    assert "code-level compatibility default `1.0`" not in safety_design_text
