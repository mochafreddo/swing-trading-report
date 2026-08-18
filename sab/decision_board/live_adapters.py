"""Concrete credentialed transports for Decision Board live shadow runs."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

import requests  # type: ignore[import-untyped]

from sab.research.deadline import Deadline
from sab.utils.bounded_process import (
    AsyncBoundedProcessRunnerV0,
    run_sync_in_bounded_process_async_v0,
)

_OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
_MAX_RESPONSE_BYTES = 1_000_000
_MAX_OPERATION_TIMEOUT_SECONDS = 15.0
type PostJsonV0 = Callable[[str, dict[str, str], dict[str, object], float], object]


@dataclass(frozen=True, slots=True)
class OpenAIResponsesTransportV0:
    """Call the fixed Responses endpoint without exposing credentials to payloads."""

    api_key: str = field(repr=False)
    post_json: PostJsonV0 = field(
        default_factory=lambda: _post_json,
        repr=False,
        compare=False,
    )
    bounded_runner: AsyncBoundedProcessRunnerV0 = field(
        default=run_sync_in_bounded_process_async_v0,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if (
            type(self.api_key) is not str
            or not self.api_key
            or self.api_key != self.api_key.strip()
            or any(ord(character) < 0x20 for character in self.api_key)
        ):
            raise ValueError("OpenAI API key is unavailable")

    async def create_response(
        self,
        request: dict[str, object],
        *,
        deadline: Deadline,
        timeout: float,
    ) -> object:
        if type(request) is not dict or type(deadline) is not Deadline:
            raise ValueError("Responses request is invalid")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("Responses timeout is invalid")
        operation_timeout = deadline.child_timeout(
            min(float(timeout), _MAX_OPERATION_TIMEOUT_SECONDS)
        )
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = await self.bounded_runner(
                self.post_json,
                (
                    _OPENAI_RESPONSES_URL,
                    headers,
                    request,
                    operation_timeout,
                ),
                timeout=operation_timeout,
            )
        except TimeoutError:
            raise
        except Exception as exc:
            raise RuntimeError("Responses transport failed") from exc
        deadline.remaining()
        if type(response) is not dict:
            raise RuntimeError("Responses transport returned invalid JSON")
        return response


def _post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    timeout: float,
) -> object:
    expires_at = time.monotonic() + timeout
    connect_timeout = timeout / 3.0
    session = requests.Session()
    session.trust_env = False
    response: requests.Response | None = None
    try:
        response = session.post(
            url,
            headers=headers,
            json=cast(Any, payload),
            timeout=(connect_timeout, timeout),
            allow_redirects=False,
            stream=True,
        )
        if response.status_code != 200:
            raise RuntimeError("Responses request was unsuccessful")
        media_type = response.headers.get("content-type", "").split(";", 1)[0]
        if media_type.strip().lower() != "application/json":
            raise RuntimeError("Responses content type is invalid")
        if time.monotonic() >= expires_at:
            raise TimeoutError("Responses request timed out")
        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if time.monotonic() >= expires_at:
                raise TimeoutError("Responses request timed out")
            body.extend(chunk)
            if len(body) > _MAX_RESPONSE_BYTES:
                raise RuntimeError("Responses body is too large")
        if time.monotonic() >= expires_at:
            raise TimeoutError("Responses request timed out")
        try:
            return json.loads(bytes(body).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Responses body is invalid JSON") from exc
    except requests.RequestException as exc:
        raise RuntimeError("Responses request failed") from exc
    finally:
        if response is not None:
            response.close()
        session.close()


__all__ = ["OpenAIResponsesTransportV0"]
