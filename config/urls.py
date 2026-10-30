"""
URL map.

Paths under `/api/` are the contract with the mobile client's
`src/api/endpoints.ts`; changing one means changing both.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from .health import healthz, readyz

api_patterns = [
    path("auth/", include("apps.accounts.urls")),
    path("leaderboard/", include("apps.leaderboard.urls")),
    path("", include("apps.decks.urls")),  # /decks/, /cards/, /uploads/
    path("", include("apps.games.urls")),  # /sessions/
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(api_patterns)),
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]

if settings.DEBUG:
    # Uploaded card art is served by object storage or the edge in production.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
