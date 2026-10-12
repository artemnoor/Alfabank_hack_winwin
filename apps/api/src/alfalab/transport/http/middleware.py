"""HTTP request size gate applied before JSON parsing."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from alfalab.execution.errors import SafeExecutionError
from alfalab.transport.errors import safe_error_body


ASGIMessage = dict[str, Any]
ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
ASGISend = Callable[[ASGIMessage], Awaitable[None]]


class BodySizeLimitMiddleware:
    def __init__(self, app: Callable[..., Awaitable[None]], maximum_bytes: int) -> None:
        self.app = app
        self.maximum_bytes = maximum_bytes

    async def __call__(self, scope: dict[str, Any], receive: ASGIReceive, send: ASGISend) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = next(
            (
                value
                for key, value in scope.get("headers", ())
                if key.lower() == b"content-length"
            ),
            None,
        )
        if content_length is not None:
            try:
                if int(content_length) > self.maximum_bytes:
                    await self._respond_too_large(send)
                    return
            except ValueError:
                await self._respond_too_large(send)
                return

        # Read the bounded body before entering the framework's JSON parser.
        # Raising from receive() can be translated into a generic malformed-body
        # response by the parser, which would hide the intended 413 envelope.
        messages: list[ASGIMessage] = []
        total_bytes = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            total_bytes += len(message.get("body", b""))
            if total_bytes > self.maximum_bytes:
                await self._respond_too_large(send)
                return
            if not message.get("more_body", False):
                break

        async def buffered_receive() -> ASGIMessage:
            if messages:
                return messages.pop(0)
            return await receive()

        await self.app(scope, buffered_receive, send)

    @staticmethod
    async def _respond_too_large(send: ASGISend) -> None:
        error = safe_error_body(
            code="REQUEST_TOO_LARGE",
            category="validation",
            safe_message="The request body exceeds the configured size limit.",
        )
        body = json.dumps(error.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})
