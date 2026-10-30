from django.urls import path

from .views import BadgeListView, LeaderboardView

app_name = "leaderboard"

urlpatterns = [
    # `badges/` must precede the list route so it isn't swallowed by it.
    path("badges/", BadgeListView.as_view(), name="badges"),
    path("", LeaderboardView.as_view(), name="list"),
]
