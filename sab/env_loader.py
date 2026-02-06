from __future__ import annotations

import os
from pathlib import Path


def load_dotenv_if_available(
    *, dotenv_path: str | os.PathLike[str] | None = None, override: bool = False
) -> None:
    if _load_with_python_dotenv(dotenv_path=dotenv_path, override=override):
        return
    _load_with_fallback_parser(dotenv_path=dotenv_path, override=override)


def _load_with_python_dotenv(
    *, dotenv_path: str | os.PathLike[str] | None = None, override: bool = False
) -> bool:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return False

    try:
        kwargs: dict[str, object] = {"override": override}
        if dotenv_path is not None:
            kwargs["dotenv_path"] = str(dotenv_path)
        load_dotenv(**kwargs)
    except Exception:
        return False
    return True


def _load_with_fallback_parser(
    *, dotenv_path: str | os.PathLike[str] | None = None, override: bool = False
) -> None:
    path = Path(dotenv_path) if dotenv_path is not None else Path(".env")
    if not path.exists():
        return

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw_line in lines:
        parsed = _parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        if not override and os.getenv(key) is not None:
            continue
        os.environ[key] = value


def _parse_env_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None

    if text.startswith("export "):
        text = text[len("export ") :].lstrip()

    if "=" not in text:
        return None

    key, value = text.split("=", 1)
    key = key.strip()
    if not key or not _is_valid_env_key(key):
        return None

    value = _strip_inline_comment(value).strip()
    value = _unquote_value(value)
    return key, value


def _is_valid_env_key(key: str) -> bool:
    if not (key[0].isalpha() or key[0] == "_"):
        return False
    return all(ch.isalnum() or ch == "_" for ch in key)


def _strip_inline_comment(value: str) -> str:
    result: list[str] = []
    in_single = False
    in_double = False
    escape = False

    for idx, ch in enumerate(value):
        if escape:
            result.append(ch)
            escape = False
            continue

        if ch == "\\":
            result.append(ch)
            escape = True
            continue

        if ch == "'" and not in_double:
            in_single = not in_single
            result.append(ch)
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
            result.append(ch)
            continue

        if ch == "#" and not in_single and not in_double:
            prev = value[idx - 1] if idx > 0 else ""
            if idx == 0 or prev.isspace():
                break

        result.append(ch)

    return "".join(result)


def _unquote_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
