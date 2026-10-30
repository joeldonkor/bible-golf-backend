"""
WSGI entrypoint.

Kept for tooling that expects one; the app is served over ASGI (`config.asgi`)
because websockets need it.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_wsgi_application()
