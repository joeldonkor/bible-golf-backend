"""
JWT authentication for websocket connections.

Browsers and React Native cannot set an `Authorization` header on a WebSocket
handshake, so the access token arrives either in the query string
(`?token=...`) or as the second `Sec-WebSocket-Protocol` value -- the two
conventions clients actually have available. Both are accepted.
"""

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

logger = logging.getLogger(__name__)


@database_sync_to_async
def _user_from_token(raw_token: str):
    from django.contrib.auth import get_user_model

    try:
        token = AccessToken(raw_token)
    except (TokenError, InvalidToken):
        return AnonymousUser()

    user_id = token.get("user_id")
    if not user_id:
        return AnonymousUser()

    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    return user or AnonymousUser()


def _extract_token(scope) -> str:
    query = parse_qs((scope.get("query_string") or b"").decode(errors="ignore"))
    token = (query.get("token") or [""])[0]
    if token:
        return token

    # Convention: ["bearer", "<jwt>"] as the requested subprotocols.
    protocols = scope.get("subprotocols") or []
    if len(protocols) >= 2 and protocols[0].lower() == "bearer":
        return protocols[1]
    return ""


class JWTAuthMiddleware(BaseMiddleware):
    """Populates `scope["user"]` from the handshake's access token."""

    async def __call__(self, scope, receive, send):
        raw_token = _extract_token(scope)
        scope["user"] = await _user_from_token(raw_token) if raw_token else AnonymousUser()
        return await super().__call__(scope, receive, send)
