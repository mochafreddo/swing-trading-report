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


def test_runbook_keeps_scheduled_ai_brief_guidance_in_scheduled_section() -> None:
    text = _read(Path("docs/runbook.md"))
    manual_section = text.split("- AI Brief 수동 실행(GitHub Actions)", 1)[1].split(
        "- AI Brief scheduled 실행", 1
    )[0]
    scheduled_section = text.split("- AI Brief scheduled 실행", 1)[1].split(
        "- Audit 실행", 1
    )[0]

    assert "scheduled 기본값" not in manual_section
    assert "AI_BRIEF_SOURCE_PROVIDER_US" in scheduled_section


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
