"""
The realtime half of the API.

One socket per player per table. Everything a player does at the board can be
done over this socket -- swing, resolve, leave -- and every result lands on all
the other sockets at that table in one hop, with no polling interval to wait
out. The REST endpoints remain as the fallback and the cold-start path, and
because both transports route through `services.py`, they cannot disagree.

Protocol
--------
Connect:  wss://host/ws/sessions/<session_id>/?token=<access JWT>
          (or with the `["bearer", "<jwt>"]` subprotocol pair)

Client -> server:
    {"action": "sync"}                                  resend current state
    {"action": "ping"}                                  keepalive
    {"action": "start"}                                 host starts the round
    {"action": "roll"}                                  take a swing
    {"action": "resolveCard", "choiceIndex": 2 | null}  settle the pending card
    {"action": "skipTurn"}                              skip a stalled player
    {"action": "leave"}                                 give up the seat

Server -> client:
    {"type": "state", "version": n, "state": {...}, "session": {...}}
    {"type": "error", "code": "...", "detail": "..."}
    {"type": "pong"}

`state` and `session` are byte-identical to the bodies of
`GET /sessions/{id}/state/` and `GET /sessions/{id}/`, so a client can feed
them straight into the caches its REST calls already fill.
"""

import logging
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework.exceptions import APIException

from . import services
from .broadcast import FRAME_ERROR, FRAME_PONG, build_state_frame, group_name
from .models import GameSession

logger = logging.getLogger(__name__)

# Close codes (4000+ is the application-defined range).
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404
CLOSE_RATE_LIMITED = 4429

# A socket may send this many actions per window before it is throttled. Turn
# actions are inherently slow, so anything above this is a buggy or hostile
# client rather than a fast player.
RATE_LIMIT_ACTIONS = 30
RATE_LIMIT_WINDOW = 10.0


class SessionConsumer(AsyncJsonWebsocketConsumer):
    """Live state for one table."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id = None
        self.group = None
        self.user = None
        self._window_started = 0.0
        self._window_count = 0

    # ---------------------------------------------------------------- lifecycle

    async def connect(self):
        self.user = self.scope.get("user")
        if self.user is None or not self.user.is_authenticated:
            await self.close(code=CLOSE_UNAUTHORIZED)
            return

        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        membership = await self._membership()
        if membership is None:
            await self.close(code=CLOSE_NOT_FOUND)
            return
        if not membership:
            await self.close(code=CLOSE_FORBIDDEN)
            return

        self.group = group_name(self.session_id)
        await self.channel_layer.group_add(self.group, self.channel_name)

        # Echo the negotiated subprotocol when the token came in that way.
        subprotocols = self.scope.get("subprotocols") or []
        await self.accept(subprotocols[0] if subprotocols else None)

        session = await database_sync_to_async(services.set_presence)(
            user_id=self.user.id, session_id=self.session_id, delta=1
        )
        if session is not None:
            # Everyone sees the presence dot go green, including this socket.
            await self._publish(session)

    async def disconnect(self, code):
        if self.group is None:
            return
        await self.channel_layer.group_discard(self.group, self.channel_name)
        session = await database_sync_to_async(services.set_presence)(
            user_id=self.user.id, session_id=self.session_id, delta=-1
        )
        if session is not None:
            await self._publish(session)

    # ------------------------------------------------------------------ inbound

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            await self._error("bad_frame", "Expected a JSON object.")
            return

        action = str(content.get("action") or "").strip()
        if action == "ping":
            await self.send_json({"type": FRAME_PONG})
            return

        if not self._allow():
            await self._error("rate_limited", "Slow down a moment.")
            await self.close(code=CLOSE_RATE_LIMITED)
            return

        handler = {
            "sync": self._handle_sync,
            "start": self._handle_start,
            "roll": self._handle_roll,
            "resolveCard": self._handle_resolve,
            "resolve_card": self._handle_resolve,
            "skipTurn": self._handle_skip,
            "skip_turn": self._handle_skip,
            "leave": self._handle_leave,
        }.get(action)

        if handler is None:
            await self._error("unknown_action", f"Unsupported action: {action!r}.")
            return

        try:
            await handler(content)
        except APIException as exc:
            # A rule violation ("not your turn") is feedback for this socket
            # only -- the table's state hasn't changed, so nobody else is told.
            await self._error(getattr(exc, "default_code", "error"), _detail_of(exc))
        except Exception:
            logger.exception(
                "ws_action_failed",
                extra={"session_id": str(self.session_id), "action": action},
            )
            await self._error("server_error", "Something went wrong. Try again.")

    # ----------------------------------------------------------------- handlers

    async def _handle_sync(self, _content):
        session = await database_sync_to_async(services.reload_for_broadcast)(self.session_id)
        await self.send_json(await self._frame(session))

    async def _handle_start(self, _content):
        await database_sync_to_async(services.start_session)(
            user=self.user, session_id=self.session_id
        )

    async def _handle_roll(self, _content):
        await database_sync_to_async(services.take_swing)(
            user=self.user, session_id=self.session_id
        )

    async def _handle_resolve(self, content):
        raw = content.get("choiceIndex", content.get("choice_index"))
        choice_index = None
        if raw is not None:
            try:
                choice_index = int(raw)
            except (TypeError, ValueError):
                await self._error("bad_choice", "choiceIndex must be a number.")
                return
        await database_sync_to_async(services.resolve_card)(
            user=self.user, session_id=self.session_id, choice_index=choice_index
        )

    async def _handle_skip(self, _content):
        await database_sync_to_async(services.skip_turn)(
            user=self.user, session_id=self.session_id
        )

    async def _handle_leave(self, _content):
        await database_sync_to_async(services.leave_session)(
            user=self.user, session_id=self.session_id
        )
        await self.close()

    # ----------------------------------------------------------------- outbound

    async def session_frame(self, message):
        """Relay a frame published by whoever performed the mutation."""
        await self.send_json(message["frame"])

    async def _publish(self, session):
        frame = await database_sync_to_async(build_state_frame)(session)
        await self.channel_layer.group_send(
            self.group, {"type": "session.frame", "frame": frame}
        )

    async def _frame(self, session) -> dict:
        return await database_sync_to_async(build_state_frame)(session)

    async def _error(self, code: str, detail: str):
        await self.send_json({"type": FRAME_ERROR, "code": code, "detail": detail})

    # ------------------------------------------------------------------ helpers

    @database_sync_to_async
    def _membership(self) -> bool | None:
        """True if seated, False if not, None if there's no such session."""
        session = GameSession.objects.filter(pk=self.session_id).first()
        if session is None:
            return None
        return session.players.filter(user=self.user).exists()

    def _allow(self) -> bool:
        now = time.monotonic()
        if now - self._window_started > RATE_LIMIT_WINDOW:
            self._window_started = now
            self._window_count = 0
        self._window_count += 1
        return self._window_count <= RATE_LIMIT_ACTIONS


def _detail_of(exc: APIException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        detail = next(iter(detail.values()), "")
    if isinstance(detail, (list, tuple)):
        detail = detail[0] if detail else ""
    return str(detail)
