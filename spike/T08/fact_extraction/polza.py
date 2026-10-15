"""Fail-closed Polza adapter pinned to the requested DeepSeek V4 Flash ID."""

from __future__ import annotations

import json
import logging
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .binding import CandidateEvent
from .allowlist import validate_approved_extraction_payload
from .errors import (
    ExtractionProviderError,
    LiveCallBudgetExceeded,
    LiveCallsDisabled,
)
from .models import ExtractedMention, ModelExtraction
from .prompt import SYSTEM_PROMPT

LOGGER = logging.getLogger(__name__)
POLZA_CHAT_COMPLETIONS_URL = "https://polza.ai/api/v1/chat/completions"
EXPECTED_MODEL_ID = "deepseek/deepseek-v4-flash"
API_KEY_ENV_VAR = "POLZA_AI_API_KEY"
REQUEST_TIMEOUT_SECONDS = 25
MAX_REQUEST_BYTES = 1_500_000
MAX_RESPONSE_BYTES = 1_048_576
MAX_COMPLETION_TOKENS = 4096


@dataclass(frozen=True)
class LiveCallAuthorization:
    """Explicit local permission object; absent authorization means zero calls."""

    approved_by_user: bool
    max_requests: int


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    final_url: str
    body: bytes


class ChatTransport(Protocol):
    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> TransportResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _PolzaHttpsTransport:
    """Pinned HTTPS transport with proxy discovery and redirects disabled."""

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> TransportResponse:
        if url != POLZA_CHAT_COMPLETIONS_URL:
            raise ExtractionProviderError("unapproved_provider_url")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirect(),
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                response_body = response.read(max_response_bytes + 1)
                if len(response_body) > max_response_bytes:
                    raise ExtractionProviderError("provider_response_too_large")
                final_url = response.geturl()
                if final_url != url:
                    raise ExtractionProviderError("provider_redirect_rejected")
                return TransportResponse(response.status, final_url, response_body)
        except urllib.error.HTTPError as exc:
            # Do not read or report the response body; it may echo article data.
            status_code = exc.code
            exc.close()
            return TransportResponse(status_code, url, b"")
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ExtractionProviderError("provider_timeout") from None
            raise ExtractionProviderError("provider_connection_failed") from None
        except TimeoutError:
            raise ExtractionProviderError("provider_timeout") from None
        except ExtractionProviderError:
            raise
        except OSError:
            raise ExtractionProviderError("provider_transport_failed") from None


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _strict_json_loads(payload: str):
    return json.loads(
        payload,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non_finite_json")),
    )


class PolzaDeepSeekFlash:
    """One request per Jev candidate; no network fallback and no implicit retries."""

    model_id = EXPECTED_MODEL_ID
    endpoint = POLZA_CHAT_COMPLETIONS_URL

    def __init__(
        self,
        *,
        api_key: str | None = None,
        authorization: LiveCallAuthorization | None = None,
    ) -> None:
        self._api_key = api_key
        self._authorization = authorization
        # Live callers cannot provide a transport: the only supported egress
        # path is the pinned HTTPS transport below. Tests may replace this
        # private seam on an already-constructed instance.
        self._transport: ChatTransport = _PolzaHttpsTransport()
        self.calls_made = 0
        self.last_usage: dict[str, int] | None = None
        self.last_cost_rub: float | None = None
        self.last_elapsed_ms: int | None = None

    @classmethod
    def from_windows_environment(
        cls,
        *,
        authorization: LiveCallAuthorization | None = None,
    ) -> "PolzaDeepSeekFlash":
        if authorization is None or authorization.approved_by_user is not True:
            raise LiveCallsDisabled("live_calls_disabled_pending_user_approval")
        key = os.environ.get(API_KEY_ENV_VAR)
        if not key:
            raise ExtractionProviderError("provider_credential_missing")
        return cls(api_key=key, authorization=authorization)

    def extract_candidate(
        self,
        *,
        case_id: str,
        article_text: str,
        classification: dict,
        candidate: CandidateEvent,
    ) -> list[ExtractedMention]:
        authorization = self._authorization
        if (
            authorization is None
            or authorization.approved_by_user is not True
            or authorization.max_requests < 1
        ):
            raise LiveCallsDisabled("live_calls_disabled_pending_user_approval")
        if self.calls_made >= authorization.max_requests:
            raise LiveCallBudgetExceeded("provider_request_limit_reached")
        if self._api_key is None:
            raise ExtractionProviderError("provider_credential_missing")
        try:
            validate_approved_extraction_payload(
                case_id=case_id,
                article_text=article_text,
                classification=classification,
                candidate=candidate,
            )
        except Exception:
            raise ExtractionProviderError("unapproved_egress_payload") from None
        if len(article_text) > 200_000 or not article_text.strip():
            raise ExtractionProviderError("article_text_out_of_bounds")
        self.calls_made += 1  # A failed attempt also consumes the authorized slot.
        request_body = self._request_body(article_text, candidate)
        if len(request_body) > MAX_REQUEST_BYTES:
            raise ExtractionProviderError("provider_request_too_large")
        transport = self._transport
        # These values belong to this attempt only. Do not accidentally carry
        # token usage or latency forward if a later provider response omits it.
        self.last_usage = None
        self.last_cost_rub = None
        self.last_elapsed_ms = None
        LOGGER.info(
            "fact_extraction.provider.request_started",
            extra={"candidate_count": 1, "model_id": self.model_id},
        )
        started = time.perf_counter()
        try:
            response = transport.post(
                url=self.endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                body=request_body,
                timeout_seconds=REQUEST_TIMEOUT_SECONDS,
                max_response_bytes=MAX_RESPONSE_BYTES,
            )
        except ExtractionProviderError:
            LOGGER.warning("fact_extraction.provider.request_failed")
            raise
        except Exception:
            LOGGER.warning("fact_extraction.provider.request_failed")
            raise ExtractionProviderError("provider_transport_failed") from None
        self.last_elapsed_ms = round((time.perf_counter() - started) * 1000)
        if response.final_url != self.endpoint:
            raise ExtractionProviderError("provider_redirect_rejected")
        if response.status_code < 200 or response.status_code >= 300:
            LOGGER.warning(
                "fact_extraction.provider.http_error",
                extra={"status_code": response.status_code},
            )
            raise ExtractionProviderError(
                "provider_http_error", status_code=response.status_code
            )
        if len(response.body) > MAX_RESPONSE_BYTES:
            raise ExtractionProviderError("provider_response_too_large")
        try:
            provider_json = _strict_json_loads(
                response.body.decode("utf-8", errors="strict")
            )
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            raise ExtractionProviderError("provider_response_invalid_json") from None
        if not isinstance(provider_json, dict):
            raise ExtractionProviderError("provider_response_schema_invalid")
        if provider_json.get("model") != self.model_id:
            raise ExtractionProviderError("provider_model_mismatch")
        choices = provider_json.get("choices")
        if (
            not isinstance(choices, list)
            or len(choices) != 1
            or not isinstance(choices[0], dict)
        ):
            raise ExtractionProviderError("provider_response_schema_invalid")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content:
            raise ExtractionProviderError("provider_response_content_missing")
        try:
            extracted = ModelExtraction.model_validate_json(content, strict=True)
        except Exception:
            raise ExtractionProviderError(
                "provider_extraction_schema_invalid"
            ) from None
        usage = provider_json.get("usage")
        if isinstance(usage, dict):
            token_usage = {
                key: value
                for key, value in usage.items()
                if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
            }
            self.last_usage = token_usage or None
            cost_rub = usage.get("cost_rub")
            if isinstance(cost_rub, (int, float)) and not isinstance(cost_rub, bool):
                try:
                    normalized_cost = float(cost_rub)
                except (OverflowError, ValueError):
                    normalized_cost = None
                if (
                    normalized_cost is not None
                    and math.isfinite(normalized_cost)
                    and normalized_cost >= 0
                ):
                    self.last_cost_rub = normalized_cost
        LOGGER.info(
            "fact_extraction.provider.request_completed",
            extra={
                "model_id": self.model_id,
                "mention_count": len(extracted.mentions),
                "elapsed_ms": self.last_elapsed_ms,
            },
        )
        return extracted.mentions

    def _request_body(self, article_text: str, candidate: CandidateEvent) -> bytes:
        user_data = {
            "fixed_event_candidate": {
                "code": candidate.code,
                "label": candidate.label,
                "definition": candidate.definition,
                "include": candidate.include,
                "exclude": candidate.exclude,
            },
            "article_text_untrusted": article_text,
        }
        body = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        user_data, ensure_ascii=False, separators=(",", ":")
                    ),
                },
            ],
            "temperature": 0,
            "max_tokens": MAX_COMPLETION_TOKENS,
        }
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
