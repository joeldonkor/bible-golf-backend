from rest_framework.routers import DefaultRouter

from .views import SessionViewSet

app_name = "games"

router = DefaultRouter()
router.register("sessions", SessionViewSet, basename="session")

urlpatterns = router.urls
