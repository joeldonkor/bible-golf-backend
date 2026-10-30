"""
Production settings.

Everything that could bite in production is asserted at import time rather than
discovered at 3am: a weak SECRET_KEY, a missing DATABASE_URL, an open host
allowlist. The process refuses to boot instead of booting insecurely.
"""

from .base import *  # noqa: F403
from .base import env  # noqa: F401

DEBUG = False

SECRET_KEY = env("DJANGO_SECRET_KEY")  # raises if unset
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")  # raises if unset

if SECRET_KEY == "insecure-dev-key-change-me" or len(SECRET_KEY) < 32:
    raise RuntimeError("DJANGO_SECRET_KEY must be a strong, unique 32+ char value.")
if "*" in ALLOWED_HOSTS:
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must name real hosts, not '*'.")

# --------------------------------------------------------------------------- #
# Transport security
# --------------------------------------------------------------------------- #

# Terminating TLS at a load balancer is the norm; trust its forwarded proto.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31_536_000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# --------------------------------------------------------------------------- #
# Data layer
# --------------------------------------------------------------------------- #

DATABASES = {"default": env.db_url("DATABASE_URL")}  # raises if unset
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=300)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DATABASES["default"].setdefault("OPTIONS", {})

# Never let a runaway query hold a connection open indefinitely. Both options
# are PostgreSQL-specific, so they're applied only when that's the backend --
# `collectstatic` during an image build points at SQLite and would otherwise
# fail on a keyword its driver has never heard of.
if "postgresql" in DATABASES["default"].get("ENGINE", ""):
    DATABASES["default"]["OPTIONS"].update(
        {
            "connect_timeout": env.int("DB_CONNECT_TIMEOUT", default=5),
            "options": "-c statement_timeout="
            + str(env.int("DB_STATEMENT_TIMEOUT_MS", default=10_000)),
        }
    )

# A read replica can be wired in later; the router lives in apps/common/db.py.
if env("DATABASE_REPLICA_URL", default=""):
    DATABASES["replica"] = env.db_url("DATABASE_REPLICA_URL")
    DATABASES["replica"]["CONN_MAX_AGE"] = DATABASES["default"]["CONN_MAX_AGE"]
    DATABASE_ROUTERS = ["apps.common.db.ReadReplicaRouter"]

# Structured logs only -- human formatting belongs in dev.
LOGGING["handlers"]["console"]["formatter"] = "json"  # noqa: F405

# --------------------------------------------------------------------------- #
# Error reporting (optional)
# --------------------------------------------------------------------------- #

SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.05),
        environment=env("SENTRY_ENVIRONMENT", default="production"),
        release=env("APP_RELEASE", default=None),
        send_default_pii=False,
    )
