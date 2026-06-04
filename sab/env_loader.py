from __future__ import annotations

import os
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

type _SuppressionState = tuple[threading.Thread, frozenset[str]]

_SUPPRESSED_CONFIG_ENV_KEYS: ContextVar[_SuppressionState | None] = ContextVar(
    "sab_suppressed_config_env_keys",
    default=None,
)


def load_dotenv_if_available(
    *, dotenv_path: str | os.PathLike[str] | None = None, override: bool = False
) -> None:
    if _python_dotenv_disabled():
        return
    suppressed_keys = _active_suppressed_env_keys()
    if not _load_with_python_dotenv(
        dotenv_path=dotenv_path,
        override=override,
        suppressed_keys=suppressed_keys,
    ):
        _load_with_fallback_parser(
            dotenv_path=dotenv_path,
            override=override,
            suppressed_keys=suppressed_keys,
        )


@contextmanager
def suppress_config_env_keys(keys: Iterable[str]) -> Iterator[None]:
    normalized = frozenset(str(key).strip() for key in keys if str(key).strip())
    if not normalized:
        yield
        return
    token = _SUPPRESSED_CONFIG_ENV_KEYS.set(
        (threading.current_thread(), _active_suppressed_env_keys() | normalized)
    )
    try:
        yield
    finally:
        _SUPPRESSED_CONFIG_ENV_KEYS.reset(token)


def getenv(name: str, default: str | None = None) -> str | None:
    key = str(name)
    if key in _active_suppressed_env_keys():
        return default
    return os.getenv(key, default)


def _active_suppressed_env_keys() -> frozenset[str]:
    state = _SUPPRESSED_CONFIG_ENV_KEYS.get()
    if state is None:
        return frozenset()
    owner_thread, keys = state
    # Python 3.14 can inherit ContextVars into new threads; this suppression
    # only applies in the thread that created it.
    if owner_thread is not threading.current_thread():
        return frozenset()
    return keys


def _python_dotenv_disabled() -> bool:
    value = os.environ.get("PYTHON_DOTENV_DISABLED")
    if value is None:
        return False
    return value.casefold() in {"1", "true", "t", "yes", "y"}


def _load_with_python_dotenv(
    *,
    dotenv_path: str | os.PathLike[str] | None = None,
    override: bool = False,
    suppressed_keys: frozenset[str] = frozenset(),
) -> bool:
    try:
        from dotenv import load_dotenv  # type: ignore
        from dotenv.main import DotEnv, find_dotenv  # type: ignore
    except Exception:
        return False

    try:
        if _python_dotenv_disabled():
            return True
        if suppressed_keys:
            resolved_path = find_dotenv() if dotenv_path is None else dotenv_path
            values = DotEnv(
                dotenv_path=resolved_path,
                verbose=False,
                interpolate=True,
                override=override,
                encoding="utf-8",
            ).dict()
            _apply_env_values(
                values,
                override=override,
                suppressed_keys=suppressed_keys,
            )
        elif dotenv_path is not None:
            load_dotenv(dotenv_path=str(dotenv_path), override=override)
        else:
            load_dotenv(override=override)
    except Exception:
        return False
    return True


def _load_with_fallback_parser(
    *,
    dotenv_path: str | os.PathLike[str] | None = None,
    override: bool = False,
    suppressed_keys: frozenset[str] = frozenset(),
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
        if not _should_apply_env_value(
            key,
            override=override,
            suppressed_keys=suppressed_keys,
        ):
            continue
        os.environ[key] = value


def _apply_env_values(
    values: Mapping[str, str | None],
    *,
    override: bool,
    suppressed_keys: frozenset[str],
) -> None:
    for key, value in values.items():
        if value is None or not _should_apply_env_value(
            key,
            override=override,
            suppressed_keys=suppressed_keys,
        ):
            continue
        os.environ[key] = value


def _should_apply_env_value(
    key: str,
    *,
    override: bool,
    suppressed_keys: frozenset[str],
) -> bool:
    if key in suppressed_keys:
        return False
    return override or os.getenv(key) is None


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


def env_flag(name: str, *, default: bool = False) -> bool:
    """환경변수 ``name``을 불리언 플래그로 해석한다.

    값이 없으면 ``default``를 반환하고, 있으면 ``1/true/yes/y/on``(대소문자
    무시)을 참으로 본다.
    """

    raw = getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
