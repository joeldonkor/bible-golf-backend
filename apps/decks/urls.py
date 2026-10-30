from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CardArtUploadView, CardViewSet, DeckViewSet

app_name = "decks"

router = DefaultRouter()
router.register("decks", DeckViewSet, basename="deck")
router.register("cards", CardViewSet, basename="card")

urlpatterns = router.urls + [
    path("uploads/card-art/", CardArtUploadView.as_view(), name="card-art-upload"),
]
