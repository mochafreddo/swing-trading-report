from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("sab", "tests")
MIN_CONFIDENCE = "80"
MULTI_EXCEPT_RE = re.compile(
    r"^(\s*)except ([A-Za-z_][\w.]*), ([A-Za-z_][\w.]*):(\s*(?:#.*)?)$",
    re.MULTILINE,
)


def _normalize_for_vulture(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    normalized = MULTI_EXCEPT_RE.sub(r"\1except (\2, \3):\4", text)
    if normalized != text:
        path.write_text(normalized, encoding="utf-8")


def _copy_sources(tmp_root: Path) -> None:
    for dirname in SOURCE_DIRS:
        source = ROOT / dirname
        destination = tmp_root / dirname
        shutil.copytree(
            source,
            destination,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        for path in destination.rglob("*.py"):
            _normalize_for_vulture(path)


def _rewrite_temp_paths(output: str, tmp_root: Path) -> str:
    return output.replace(f"{tmp_root}/", "")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sab-vulture-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        _copy_sources(tmp_root)
        command = [
            sys.executable,
            "-m",
            "vulture",
            str(tmp_root / "sab"),
            str(tmp_root / "tests"),
            "--min-confidence",
            MIN_CONFIDENCE,
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        sys.stdout.write(_rewrite_temp_paths(result.stdout, tmp_root))
        sys.stderr.write(_rewrite_temp_paths(result.stderr, tmp_root))
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
