from __future__ import annotations

import json
from pathlib import Path

import pytest
from sab.data.cache import save_json
from sab.utils import atomic_io
from sab.utils.atomic_io import atomic_write_json


def _tmp_files_for(path: Path) -> list[Path]:
    return list(path.parent.glob(f".{path.name}.*.tmp"))


def test_save_json_keeps_previous_content_on_dump_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_dir = tmp_path.as_posix()
    save_json(base_dir, "sample", {"version": "old"})
    target = tmp_path / "sample.json"

    original_dump = atomic_io.json.dump

    def _failing_dump(obj, fp, *args, **kwargs):
        if obj == {"version": "new"}:
            raise RuntimeError("forced dump failure")
        return original_dump(obj, fp, *args, **kwargs)

    monkeypatch.setattr(atomic_io.json, "dump", _failing_dump)

    with pytest.raises(RuntimeError, match="forced dump failure"):
        save_json(base_dir, "sample", {"version": "new"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"version": "old"}
    assert _tmp_files_for(target) == []


def test_atomic_write_json_cleans_temp_file_on_success(tmp_path: Path) -> None:
    target = tmp_path / "payload.json"

    atomic_write_json(target.as_posix(), {"ok": True})

    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
    assert _tmp_files_for(target) == []
