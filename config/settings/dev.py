"""Local development settings: SQLite + in-memory infrastructure by default."""

from .base import *  # noqa: F403
from .base import env  # noqa: F401

DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = ["*"]

# Expo dev clients and the web build hit the API from arbitrary origins.
CORS_ALLOW_ALL_ORIGINS = True

# Redis is optional locally. Without it, cache and channel layer run in-process,
# which works for a single `uvicorn` worker -- exactly the dev setup.
if not env.bool("USE_REDIS", default=False):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "biblegolf-dev",
        }
    }
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# Uploaded card art is served by Django itself in dev (see config/urls.py).
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="http://localhost:8000")

# Manifest static storage requires `collectstatic`; plain storage is friendlier.
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"
}

# Rate limits get in the way while iterating.
REST_FRAMEWORK = {**REST_FRAMEWORK}  # noqa: F405
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    key: env("THROTTLE_" + key.upper(), default=None)
    for key in ("auth", "register", "join", "turn", "write")
}
