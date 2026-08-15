"""Offline-decodable Responses transport seam for claim verification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from sab.research.deadline import Deadline

from .claims import MAX_CLAIM_TEXT_CHARS, ClaimVerifierRequestV0

MAX_CLAIM_ARTICLE_TEXT_CHARS = 100_000

_RESPONSE_REQUIRED = {
    "id",
    "object",
    "created_at",
    "status",
    "error",
    "incomplete_details",
    "model",
    "output",
}
_RESPONSE_OPTIONAL = {
    "background",
    "conversation",
    "instructions",
    "max_output_tokens",
    "max_tool_calls",
    "metadata",
    "parallel_tool_calls",
    "previous_response_id",
    "prompt",
    "prompt_cache_key",
    "prompt_cache_retention",
    "reasoning",
    "safety_identifier",
    "service_tier",
    "store",
    "temperature",
    "text",
    "tool_choice",
    "tools",
    "top_logprobs",
    "top_p",
    "truncation",
    "usage",
    "user",
}
_MESSAGE_FIELDS = {"id", "type", "status", "role", "content"}
_CONTENT_FIELDS = {"type", "annotations", "logprobs", "text"}
_CLAIM_RESULT_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "entailment",
        "supporting_span",
        "supporting_location",
        "verifier_version",
    ],
    "properties": {
        "entailment": {
            "type": "string",
            "enum": ["SUPPORTED", "CONTRADICTED", "UNCLEAR"],
        },
        "supporting_span": {"type": "string"},
        "supporting_location": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "start", "end"],
            "properties": {
                "kind": {"const": "TEXT_OFFSETS"},
                "start": {"type": "integer", "minimum": 0},
                "end": {"type": "integer", "minimum": 0},
            },
        },
        "verifier_version": {"type": "string"},
    },
}


class ResponsesClaimTransportV0(Protocol):
    """Injected transport; networking and credentials remain outside this module."""

    async def create_response(
        self,
        request: dict[str, object],
        *,
        deadline: Deadline,
        timeout: float,
    ) -> object: ...


class ClaimResponseOutputError(ValueError):
    """The response envelope is valid but its structured text is malformed."""


def build_claim_responses_request_v0(
    request: ClaimVerifierRequestV0,
    *,
    model: str,
) -> dict[str, object]:
    if type(request) is not ClaimVerifierRequestV0:
        raise TypeError("claim request must use the exact public verifier type")
    if (
        type(request.claim_text) is not str
        or not request.claim_text
        or len(request.claim_text) > MAX_CLAIM_TEXT_CHARS
        or type(request.article_text) is not str
        or not request.article_text
        or len(request.article_text) > MAX_CLAIM_ARTICLE_TEXT_CHARS
    ):
        raise ValueError("claim request text exceeds the safe bound")
    if type(model) is not str or not model or len(model) > 200:
        raise ValueError("model identity is invalid")
    return {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(
                            request.to_public_dict(),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                ],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "decision_board_claim_validation_v0",
                "strict": True,
                "schema": _CLAIM_RESULT_SCHEMA,
            }
        },
    }


def decode_claim_response_v0(
    response: object, *, expected_model: str
) -> dict[str, object]:
    """Decode one sanitized official-like completed Response without SDK/network."""

    if type(response) is not dict:
        raise ValueError("response must be an object")
    fields = set(response)
    if not fields >= _RESPONSE_REQUIRED or fields - (
        _RESPONSE_REQUIRED | _RESPONSE_OPTIONAL
    ):
        raise ValueError("response fields are invalid")
    if (
        response["object"] != "response"
        or response["status"] != "completed"
        or type(response["created_at"]) not in {int, float}
        or response["error"] is not None
        or response["incomplete_details"] is not None
        or response["model"] != expected_model
        or type(response["id"]) is not str
    ):
        raise ValueError("response identity is invalid")
    output = response["output"]
    if type(output) is not list or len(output) != 1:
        raise ValueError("response output is invalid")
    message = output[0]
    if (
        type(message) is not dict
        or set(message) != _MESSAGE_FIELDS
        or type(message["id"]) is not str
        or message["type"] != "message"
        or message["status"] != "completed"
        or message["role"] != "assistant"
    ):
        raise ValueError("response message is invalid")
    content = message["content"]
    if type(content) is not list or len(content) != 1:
        raise ValueError("response content is invalid")
    part = content[0]
    if (
        type(part) is not dict
        or set(part) != _CONTENT_FIELDS
        or part["type"] != "output_text"
        or part["annotations"] != []
        or part["logprobs"] != []
        or type(part["text"]) is not str
    ):
        raise ValueError("response text is invalid")
    try:
        decoded = json.loads(part["text"])
    except json.JSONDecodeError as exc:
        raise ClaimResponseOutputError("response text is not JSON") from exc
    if type(decoded) is not dict:
        raise ClaimResponseOutputError("response text must decode to an object")
    return decoded


@dataclass(frozen=True, slots=True)
class ResponsesClaimVerifierV0:
    transport: ResponsesClaimTransportV0
    model: str

    async def verify(
        self,
        request: ClaimVerifierRequestV0,
        *,
        deadline: Deadline,
        timeout: float,
    ) -> object:
        wire_request = build_claim_responses_request_v0(request, model=self.model)
        response = await self.transport.create_response(
            wire_request,
            deadline=deadline,
            timeout=timeout,
        )
        try:
            return decode_claim_response_v0(response, expected_model=self.model)
        except ClaimResponseOutputError:
            return {}


__all__ = [
    "ClaimResponseOutputError",
    "ResponsesClaimTransportV0",
    "ResponsesClaimVerifierV0",
    "build_claim_responses_request_v0",
    "decode_claim_response_v0",
]
