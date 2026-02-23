from __future__ import annotations

import ast
import re
from pathlib import Path


def _collect_cli_subcommands_from_main() -> set[str]:
    tree = ast.parse(Path("sab/__main__.py").read_text(encoding="utf-8"))
    commands: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_parser"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "sub"
        ):
            continue
        if (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            commands.add(node.args[0].value)

    return commands


def _extract_cli_subcommands_from_readme(readme_text: str) -> set[str]:
    start_marker = "<!-- CLI_SUBCOMMANDS_START -->"
    end_marker = "<!-- CLI_SUBCOMMANDS_END -->"
    start = readme_text.find(start_marker)
    end = readme_text.find(end_marker)

    assert start != -1 and end != -1 and start < end, (
        "README.md에 CLI 명령 표 마커가 없습니다. "
        "CLI_SUBCOMMANDS_START/END 구간을 유지하세요."
    )

    table = readme_text[start + len(start_marker) : end]
    # 표의 실행 예시는 `sab <cmd>` 또는 `... sab <cmd> ...` 형태 모두 허용한다.
    return set(re.findall(r"`[^`]*\bsab\s+([a-z0-9_-]+)\b[^`]*`", table))


def test_readme_cli_subcommands_stay_in_sync_with_parser() -> None:
    parser_commands = _collect_cli_subcommands_from_main()
    readme_commands = _extract_cli_subcommands_from_readme(
        Path("README.md").read_text(encoding="utf-8")
    )

    missing_in_readme = sorted(parser_commands - readme_commands)
    stale_in_readme = sorted(readme_commands - parser_commands)

    assert missing_in_readme == [], (
        "CLI 파서에 있지만 README 명령 표에 없는 서브커맨드가 있습니다: "
        f"{missing_in_readme}"
    )
    assert stale_in_readme == [], (
        "README 명령 표에 있지만 CLI 파서에 없는 서브커맨드가 있습니다: "
        f"{stale_in_readme}"
    )
