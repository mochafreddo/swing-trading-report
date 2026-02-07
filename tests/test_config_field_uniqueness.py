from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path


def test_config_dataclass_has_no_duplicate_field_names() -> None:
    source_path = Path(__file__).resolve().parents[1] / "sab" / "config.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))

    config_class = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "Config"
    )

    names: list[str] = []
    for stmt in config_class.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names.append(stmt.target.id)

    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    assert duplicates == []
