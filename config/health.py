"""
Liveness and readiness probes.

`/healthz` answers "is this process alive" and must stay dependency-free, or a
database blip will have the orchestrator restarting healthy pods. `/readyz`
answers "should traffic be routed here" and does check the dependencies, so a
pod that lost Redis is pulled from the load balancer instead of failing
requests.
"""

import logging

from django.core.cache import cache
from django.db import connections
from django.http import JsonResponse

logger = logging.getLogger(__name__)


def healthz(_request):
    return JsonResponse({"status": "ok"})


def readyz(_request):
    checks: dict[str, str] = {}
    ready = True

    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc.__class__.__name__}"
        ready = False

    try:
        cache.set("readyz", "1", 5)
        # django-redis is configured to swallow errors, so a silent miss is
        # itself the signal that the cache is gone.
        checks["cache"] = "ok" if cache.get("readyz") == "1" else "degraded"
    except Exception as exc:
        checks["cache"] = f"error: {exc.__class__.__name__}"

    if not ready:
        logger.error("readiness_failed", extra={"checks": checks})
    return JsonResponse({"ready": ready, "checks": checks}, status=200 if ready else 503)
