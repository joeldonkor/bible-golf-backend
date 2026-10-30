from django.urls import path

from .consumers import SessionConsumer

websocket_urlpatterns = [
    path("ws/sessions/<uuid:session_id>/", SessionConsumer.as_asgi()),
]
