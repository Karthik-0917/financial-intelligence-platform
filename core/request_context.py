import logging
import re
import time
from contextvars import ContextVar
from uuid import uuid4

_REQUEST_ID = ContextVar("financial_request_id", default=None)
VALID_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")

log = logging.getLogger(__name__)


def get_request_id():
    return _REQUEST_ID.get() or uuid4().hex


class RequestContextMiddleware:
    def __init__(self, app, *, service, accept_request_id=False):
        self.app = app
        self.service = service
        self.accept_request_id = accept_request_id

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None

        if self.accept_request_id:
            values = [
                value.decode("ascii", errors="ignore")
                for name, value in scope.get("headers", [])
                if name.lower() == b"x-request-id"
            ]

            if len(values) == 1 and VALID_REQUEST_ID.fullmatch(values[0]):
                incoming = values[0]

        request_id = incoming or uuid4().hex
        token = _REQUEST_ID.set(request_id)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message):
            nonlocal status

            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                message = {
                    **message,
                    "headers": [
                        *headers,
                        (b"x-request-id", request_id.encode("ascii")),
                    ],
                }

            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            log.info(
                "request_id=%s service=%s method=%s status=%s latency_ms=%.2f",
                request_id,
                self.service,
                scope.get("method", ""),
                status,
                (time.perf_counter() - started) * 1000,
            )
            _REQUEST_ID.reset(token)
