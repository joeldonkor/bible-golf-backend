"""
ASGI entrypoint -- HTTP and WebSocket in one process.

`get_asgi_application()` is called before the routing import on purpose: it
populates the app registry, and the consumer modules import models.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402

django_asgi_app = get_asgi_application()

from apps.common.ws_auth import JWTAuthMiddleware  # noqa: E402
from apps.games.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # A websocket handshake carries no CSRF token, so the origin check is
        # what stops a hostile page opening a socket with a user's cookies.
        # Native clients send no Origin at all and pass through.
        "websocket": AllowedHostsOriginValidator(
            JWTAuthMiddleware(URLRouter(websocket_urlpatterns))
        ),
    }
)
