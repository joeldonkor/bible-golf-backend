"""
Settings shared by every environment.

Configuration is read from the environment (12-factor); `.env` is loaded only as
a developer convenience. Anything environment-specific lives in `dev.py` /
`prod.py` / `test.py`, which import everything from here.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
# Local convenience only: in production the process environment is the source
# of truth and no .env file is shipped.
if (BASE_DIR / ".env").exists():
    env.read_env(str(BASE_DIR / ".env"))

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "channels",
    "drf_spectacular",
]

LOCAL_APPS = [
    "apps.common",
    "apps.accounts",
    "apps.decks",
    "apps.games",
    "apps.leaderboard",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "apps.common.middleware.RequestIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #

# `DATABASE_URL` drives everything: postgres://... in prod, sqlite:// locally.
DATABASES = {
    "default": env.db_url(
        "DATABASE_URL",
        default="sqlite:///" + str(BASE_DIR / "db.sqlite3"),
    )
}
# Persistent connections are the single biggest latency win for a chatty API.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    # 6 characters is what the mobile client's zod schema enforces; keeping the
    # server in step avoids errors the user can't see coming.
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 6},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------- #
# Cache / channel layer
# --------------------------------------------------------------------------- #

REDIS_URL = env("REDIS_URL", default="redis://127.0.0.1:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "IGNORE_EXCEPTIONS": True,  # a cache outage degrades, never 500s
            "CONNECTION_POOL_KWARGS": {"max_connections": 100},
        },
        "KEY_PREFIX": "biblegolf",
    }
}
DJANGO_REDIS_IGNORE_EXCEPTIONS = True

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
            # Bounded queues: a slow consumer gets dropped rather than allowed
            # to back-pressure the whole group broadcast.
            "capacity": 1500,
            "expiry": 10,
        },
    }
}

# --------------------------------------------------------------------------- #
# REST framework
# --------------------------------------------------------------------------- #

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    # The mobile client speaks camelCase end to end.
    "DEFAULT_RENDERER_CLASSES": (
        "djangorestframework_camel_case.render.CamelCaseJSONRenderer",
    ),
    "DEFAULT_PARSER_CLASSES": (
        "djangorestframework_camel_case.parser.CamelCaseJSONParser",
        "djangorestframework_camel_case.parser.CamelCaseMultiPartParser",
    ),
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ("rest_framework.throttling.ScopedRateThrottle",),
    "DEFAULT_THROTTLE_RATES": {
        "auth": env("THROTTLE_AUTH", default="20/min"),
        "register": env("THROTTLE_REGISTER", default="10/hour"),
        "join": env("THROTTLE_JOIN", default="30/min"),
        "turn": env("THROTTLE_TURN", default="120/min"),
        "write": env("THROTTLE_WRITE", default="60/min"),
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Bible Golf API",
    "DESCRIPTION": "REST + WebSocket backend for the Bible Golf mobile app.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.contrib.djangorestframework_camel_case.camelize_serializer_fields",
    ],
    "SCHEMA_PATH_PREFIX": "/api",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=30)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=30)),
    # The client stores one refresh token for the life of the session and never
    # replaces it, so rotation would invalidate it mid-flight.
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,  # avoids a write on every token issue
    "ALGORITHM": "HS256",
    "SIGNING_KEY": env("JWT_SIGNING_KEY", default=SECRET_KEY),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_TYPE_CLAIM": "token_type",
}

# --------------------------------------------------------------------------- #
# CORS
# --------------------------------------------------------------------------- #

# Expo/React Native issues requests without an Origin, so CORS matters only for
# the web build and local tooling.
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=False)
CORS_ALLOW_CREDENTIALS = False

# --------------------------------------------------------------------------- #
# i18n / static / media
# --------------------------------------------------------------------------- #

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = env("MEDIA_URL", default="/media/")
MEDIA_ROOT = BASE_DIR / "media"
# Absolute base used to build public URLs for uploaded card art.
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="").rstrip("/")

# Card art upload guard-rail. The accepted formats are decided by decoding the
# file (see `apps.decks.views.FORMAT_EXTENSIONS`), not by configuration.
MAX_CARD_ART_BYTES = env.int("MAX_CARD_ART_BYTES", default=5 * 1024 * 1024)

# --------------------------------------------------------------------------- #
# Game rules (must mirror the client's `src/constants/game.ts`)
# --------------------------------------------------------------------------- #

TOTAL_SPACES = env.int("GAME_TOTAL_SPACES", default=68)
LADDER_STEPS = env.int("GAME_LADDER_STEPS", default=7)
LADDER_ROLL_TO_ENTER = env.int("GAME_LADDER_ROLL", default=6)
DIE_SIDES = env.int("GAME_DIE_SIDES", default=6)
# How long a player may sit on their turn before anyone can skip them.
TURN_TIMEOUT_SECONDS = env.int("GAME_TURN_TIMEOUT_SECONDS", default=90)

# --------------------------------------------------------------------------- #
# Logging -- structured JSON so a log pipeline can index it.
# --------------------------------------------------------------------------- #

LOG_LEVEL = env("DJANGO_LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "apps.common.logging.RequestIDFilter"}},
    "formatters": {
        "json": {"()": "apps.common.logging.JSONFormatter"},
        "console": {
            "format": "%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s"
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": env("DJANGO_LOG_FORMAT", default="console"),
            "filters": ["request_id"],
        }
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "propagate": True},
        "apps": {"level": LOG_LEVEL, "propagate": True},
    },
}

# --------------------------------------------------------------------------- #
# Email (Brevo SMTP)
# --------------------------------------------------------------------------- #

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("BREVO_SMTP_HOST", default="smtp-relay.brevo.com")
EMAIL_PORT = env.int("BREVO_EMAIL_PORT", default=587)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = env("BREVO_SMTP_LOGIN", default="")
EMAIL_HOST_PASSWORD = env("BREVO_SMTP_KEY", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Bible Golf <noreply@biblegolf.app>")

# --------------------------------------------------------------------------- #
# Security defaults (tightened further in prod.py)
# --------------------------------------------------------------------------- #

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
# The API is stateless and token-authenticated; cookies exist only for /admin.
SESSION_COOKIE_SAMESITE = "Lax"
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
