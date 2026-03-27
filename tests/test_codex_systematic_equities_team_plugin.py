from __future__ import annotations

import json
from pathlib import Path

PLUGIN_ROOT = Path("plugins/systematic-equities-team")
PLUGIN_MANIFEST = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
MARKETPLACE_MANIFEST = Path(".agents/plugins/marketplace.json")
TEAM_DOC = Path("docs/codex-systematic-equities-team.md")

EXPECTED_SKILLS = {
    "swing-data-backtest-engineer": "데이터 정합성, 백테스트, 재현성",
    "swing-quant-researcher": "신호 로직, 시장 레짐, 가설 검증",
    "swing-risk-portfolio-manager": "리스크, 익절/손절, 포지션 규율",
}


def _read_skill_frontmatter(skill_dir: Path) -> dict[str, str]:
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{skill_dir}/SKILL.md frontmatter가 없습니다."

    _, frontmatter, _ = text.split("---", 2)
    parsed: dict[str, str] = {}

    for raw_line in frontmatter.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip().strip('"').strip("'")

    assert "name" in parsed and "description" in parsed, (
        f"{skill_dir}/SKILL.md frontmatter에 name/description이 없습니다."
    )
    return parsed


def test_systematic_equities_team_plugin_and_skills_exist() -> None:
    assert PLUGIN_MANIFEST.exists(), "Codex team plugin manifest가 없습니다."
    assert MARKETPLACE_MANIFEST.exists(), "Codex marketplace manifest가 없습니다."
    assert TEAM_DOC.exists(), "Codex team 사용 문서가 없습니다."

    plugin = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    assert plugin["name"] == "systematic-equities-team"
    assert plugin["skills"] == "./skills/"

    marketplace = json.loads(MARKETPLACE_MANIFEST.read_text(encoding="utf-8"))
    entries = {entry["name"]: entry for entry in marketplace["plugins"]}
    assert "systematic-equities-team" in entries
    assert entries["systematic-equities-team"]["source"]["path"] == (
        "./plugins/systematic-equities-team"
    )

    skills_root = PLUGIN_ROOT / "skills"
    actual_skill_names = {path.name for path in skills_root.iterdir() if path.is_dir()}
    assert actual_skill_names == set(EXPECTED_SKILLS)

    for skill_name, description_hint in EXPECTED_SKILLS.items():
        skill_dir = skills_root / skill_name
        frontmatter = _read_skill_frontmatter(skill_dir)

        assert frontmatter["name"] == skill_name
        assert description_hint in str(frontmatter["description"])
        assert (skill_dir / "agents" / "openai.yaml").exists(), (
            f"{skill_name} openai.yaml이 없습니다."
        )


def test_docs_index_links_team_doc() -> None:
    docs_index = Path("docs/README.md").read_text(encoding="utf-8")
    assert "codex-systematic-equities-team.md" in docs_index
