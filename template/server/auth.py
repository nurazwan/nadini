"""Optional bearer-token auth (enabled when AUTH_TOKEN is set)."""

import hmac

from starlette.types import ASGIApp, Receive, Scope, Send

# Paths that never require auth.
PUBLIC_PREFIXES = ("/healthz", "/readyz", "/.well-known/", "/dev-ui")


class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp, token: str | None) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.token or scope["type"] != "http" or scope["path"].startswith(PUBLIC_PREFIXES):
            return await self.app(scope, receive, send)

        headers = dict(scope["headers"])
        supplied = headers.get(b"authorization", b"").decode()
        if hmac.compare_digest(supplied, f"Bearer {self.token}"):
            return await self.app(scope, receive, send)

        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
