from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from urllib.parse import urlparse


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(override=False)
    except Exception:
        # dotenv is optional; ignore if missing
        pass


@dataclass(frozen=True)
class Config:
    data_provider: str = "kis"  # or pykrx
    kis_app_key: Optional[str] = None
    kis_app_secret: Optional[str] = None
    kis_base_url: Optional[str] = None
    screen_limit: int = 30
    report_dir: str = "reports"
    data_dir: str = "data"
    screener_enabled: bool = False
    screener_limit: int = 20
    screener_only: bool = False


def _normalize_kis_base(url: Optional[str]) -> Optional[str]:
    if not url:
        return None

    url = url.strip()
    if not url:
        return None

    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url}"

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        return url.rstrip("/")

    host = parsed.hostname.lower()
    port = parsed.port
    if port is None:
        if "openapivts" in host:
            port = 29443
        else:
            port = 9443

    netloc = parsed.hostname if port in (80, 443) else f"{parsed.hostname}:{port}"
    normalized = f"{parsed.scheme}://{netloc}"
    return normalized.rstrip("/")


def load_config(
    *,
    provider_override: Optional[str] = None,
    limit_override: Optional[int] = None,
) -> Config:
    _load_dotenv_if_available()

    provider = (provider_override or os.getenv("DATA_PROVIDER") or "kis").lower()
    try:
        limit_env = int(os.getenv("SCREEN_LIMIT", "30"))
    except ValueError:
        limit_env = 30

    screen_limit = limit_override if limit_override is not None else limit_env

    screener_enabled = os.getenv("SCREENER_ENABLED", "false").lower() in {"1", "true", "yes"}
    try:
        screener_limit = int(os.getenv("SCREENER_LIMIT", "20"))
    except ValueError:
        screener_limit = 20
    screener_only = os.getenv("SCREENER_ONLY", "false").lower() in {"1", "true", "yes"}

    return Config(
        data_provider=provider,
        kis_app_key=os.getenv("KIS_APP_KEY"),
        kis_app_secret=os.getenv("KIS_APP_SECRET"),
        kis_base_url=_normalize_kis_base(os.getenv("KIS_BASE_URL")),
        screen_limit=screen_limit,
        report_dir=os.getenv("REPORT_DIR", "reports"),
        data_dir=os.getenv("DATA_DIR", "data"),
        screener_enabled=screener_enabled,
        screener_limit=screener_limit,
        screener_only=screener_only,
    )


def load_watchlist(path: Optional[str]) -> list[str]:
    if not path:
        return []
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        tickers: list[str] = []
        for line in f:
            t = line.strip()
            if not t or t.startswith("#"):
                continue
            tickers.append(t)
    return tickers
