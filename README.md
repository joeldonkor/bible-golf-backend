# Bible Golf — Backend

Django + DRF + Channels API for the Bible Golf mobile app. Deployed separately
from the Expo client; the two meet only at the HTTP and WebSocket contract
described below.

| Concern      | Choice                                                     |
| ------------ | ---------------------------------------------------------- |
| Runtime      | Python 3.13 · Django 6.1 · ASGI                             |
| REST         | Django REST Framework 3.18 (camelCase in and out)           |
| Realtime     | Django Channels 4 over Redis                                |
| Auth         | SimpleJWT (access + refresh, blacklist on sign-out)         |
| Data         | PostgreSQL (SQLite locally)                                 |
| Cache / bus  | Redis (`django-redis` cache, `channels_redis` channel layer)|
| Serving      | gunicorn supervising uvicorn ASGI workers, behind nginx     |
| Docs         | OpenAPI 3 at `/api/schema/`, Swagger UI at `/api/docs/`     |

---

## Quick start

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate elsewhere
pip install -r requirements/dev.txt

cp .env.example .env
python manage.py migrate
python manage.py seed_content   # built-in decks, cards and badges
python manage.py createsuperuser

python -m uvicorn config.asgi:application --reload --port 8000
```

`uvicorn` — not `runserver` — because websockets need ASGI. Out of the box this
uses SQLite and in-process cache/channel layer, so nothing else has to be
running. Set `USE_REDIS=true` once you want a second worker.

Point the app at it:

```bash
# Bible Golf/.env
EXPO_PUBLIC_API_URL=http://localhost:8000/api
EXPO_PUBLIC_USE_MOCKS=false
```

On a physical device, `localhost` is the phone. Use your machine's LAN IP
(`http://192.168.x.x:8000/api`) and add it to `DJANGO_ALLOWED_HOSTS`.

### The whole stack

```bash
docker compose up --build
docker compose exec api python manage.py migrate
docker compose exec api python manage.py seed_content
```

That runs PostgreSQL, Redis, **two** API replicas and nginx on `:8000`. Two
replicas on purpose: they prove a move made on one process reaches a socket held
by the other, which is the only reason realtime goes through Redis rather than
process memory.

### Tests

```bash
pytest                       # 97 tests (one is PostgreSQL-only)
pytest --cov                 # with coverage
ruff check . && ruff format --check .
```

---

## Layout

```
backend/
├── config/
│   ├── settings/        base · dev · prod · test
│   ├── asgi.py          HTTP + WebSocket entrypoint
│   ├── urls.py          /api/... — the contract with src/api/endpoints.ts
│   └── health.py        /healthz (liveness) · /readyz (readiness)
├── apps/
│   ├── common/          base models, pagination, errors, logging, row locks,
│   │                    websocket JWT middleware
│   ├── accounts/        User, Congregation, auth endpoints, level thresholds
│   ├── decks/           Deck, Card, card authoring, art upload, seed command
│   ├── games/           GameSession, Player, GameEvent, the rules engine,
│   │                    REST views and the websocket consumer
│   └── leaderboard/     Badge, UserBadge, ranking queries
├── deploy/nginx.conf
├── tests/
└── requirements/        base · dev · prod
```

### Where the game rules live

```
apps/games/engine.py     the rules: roll, draw, resolve, advance, complete
apps/games/services.py   lock → engine → event log → broadcast
apps/games/views.py      REST transport
apps/games/consumers.py  WebSocket transport
```

Both transports call `services.py`, so a swing taken over a socket and a swing
taken over HTTP follow the identical path. That is deliberate: the alternative
is two implementations of the rules that drift apart the first time one of them
is fixed.

`engine.py` is the server-side twin of the client's
`src/services/sessions/gameEngine.ts`, with one intended difference — the
client's mock returns every turn to the local human and simulates opponents,
while the server rotates the turn between real players. The client already
disables "Take Swing" unless `activePlayerId` is yours, so nothing in the UI
has to change.

---

## API

Everything under `/api/` requires `Authorization: Bearer <access>` except
`register`, `login` and `refresh`.

| Method | Path | Returns |
| ------ | ---- | ------- |
| POST | `/api/auth/register/` | `AuthSession` |
| POST | `/api/auth/login/` | `AuthSession` |
| POST | `/api/auth/refresh/` | `{ access }` |
| GET / PATCH | `/api/auth/me/` | `User` |
| POST | `/api/auth/logout/` | `204` |
| GET / POST | `/api/decks/` | `Paginated<Deck>` / `Deck` |
| GET | `/api/decks/{id}/` | `Deck` |
| GET | `/api/decks/{id}/cards/` | `Paginated<Card>` |
| POST | `/api/cards/` | `Card` |
| DELETE | `/api/cards/{id}/` | `204` (soft delete) |
| POST | `/api/uploads/card-art/` | `{ url }` |
| GET / POST | `/api/sessions/` | `Paginated<Session>` / `Session` |
| GET | `/api/sessions/active/` | `Session \| null` |
| POST | `/api/sessions/join/` | `Session` |
| GET | `/api/sessions/{id}/` | `Session` |
| POST | `/api/sessions/{id}/start/` | `GameState` |
| GET | `/api/sessions/{id}/state/` | `GameState` |
| POST | `/api/sessions/{id}/roll/` | `GameState` |
| POST | `/api/sessions/{id}/resolve-card/` | `GameState` |
| POST | `/api/sessions/{id}/skip-turn/` | `GameState` |
| POST | `/api/sessions/{id}/leave/` | `204` |
| GET | `/api/sessions/{id}/events/` | cursor-paginated replay log |
| GET | `/api/leaderboard/?scope=` | `Paginated<LeaderboardEntry>` |
| GET | `/api/leaderboard/badges/` | `Paginated<Badge>` |

Every path `src/api/endpoints.ts` already calls is here, in the shapes
`src/types/*.ts` already declare. `tests/test_contract.py` asserts the
exact key set of every response, so a field cannot be renamed here without a
red test pointing at the app.

### Conventions worth knowing

- **camelCase both ways.** The renderer and parser translate, including inside
  JSON columns, so a card's `effect` arrives as `{ move, points, skipTurn }`.
- **`Session.hostId` is a Player id, not a user id** — `LobbyScreen` resolves
  the host with `players.find(p => p.id === session.hostId)`.
- **Errors** always carry a string `detail` plus a `code`, and validation
  failures add one camelCased key per field holding a list of messages. That is
  exactly what `src/api/errors.ts` and `applyApiError` read.
- **`/sessions/active/` returns a literal `null`** when there is no round in
  progress, not an empty body — the client's type there is `Session | null`.
- **Pagination** is `{count, next, previous, results}`; `pageSize` overrides the
  page length (`page_size` also works). The event log uses a keyset cursor
  instead, which stays fast as history grows.

---

## Realtime

```
wss://api.example.com/ws/sessions/<session_id>/?token=<access JWT>
```

The token may also be sent as the `["bearer", "<jwt>"]` subprotocol pair —
browsers and React Native cannot set an `Authorization` header on a WebSocket
handshake, so one of the two is necessary.

**Client → server**

```json
{"action": "sync"}
{"action": "ping"}
{"action": "start"}
{"action": "roll"}
{"action": "resolveCard", "choiceIndex": 2}
{"action": "skipTurn"}
{"action": "leave"}
```

**Server → client**

```json
{"type": "state", "version": 7, "state": { ...GameState }, "session": { ...Session }, "event": null}
{"type": "error", "code": "domain_error", "detail": "It isn't your turn yet."}
{"type": "pong"}
```

`state` and `session` are byte-identical to the bodies of
`GET /sessions/{id}/state/` and `GET /sessions/{id}/`, so a frame can be fed
straight into the same React Query caches the REST calls fill:

```ts
queryClient.setQueryData(queryKeys.sessions.state(id), frame.state);
queryClient.setQueryData(queryKeys.sessions.detail(id), frame.session);
```

Closing codes: `4401` no/invalid token, `4403` not seated at that table,
`4404` no such table, `4429` too many actions.

### Guarantees

- **Ordering.** `version` is monotonic and is also the sequence number of the
  session's newest event. Drop any frame whose `version` is not greater than the
  last one you applied and reordering becomes a non-issue.
- **Catch-up.** A client that was offline can `{"action": "sync"}` for current
  state, or read `/sessions/{id}/events/` for everything it missed.
- **Presence.** `player.isConnected` counts open sockets rather than flipping a
  boolean, so a phone that backgrounds and resumes doesn't flicker offline.
- **Fallback.** Every action exists over HTTP too. If sockets are blocked on a
  network, the app still works by polling — just less immediately.
- **Turn safety.** Every mutation takes a row lock on the session, so two
  players tapping at the same instant produce one move, not two.

---

## Performance notes

What was done, and why it was worth doing:

- **Fan-out does no database work.** The state frame is rendered once by
  whoever made the move and shipped through the channel layer fully formed.
  Adding a player to a table costs one Redis publish and one socket write —
  not another round of queries per listener.
- **Persistent connections** (`CONN_MAX_AGE`) and a `statement_timeout`, so
  connection setup isn't paid per request and no query can hold one forever.
- **One query per response.** `with_related()` pulls the deck, host, pending
  card and every player with their user in a single round trip; a table of six
  serialises without an N+1.
- **Indexes on the real access paths**: session by code, players by user,
  events by `(session, -sequence)`, the card draw pool, and a covering index for
  the leaderboard's `ORDER BY points DESC`.
- **Ranks from a window function**, so page 3 of a leaderboard reads 51–75
  rather than restarting at 1 — and the caller's own row is fetched by count,
  not by re-running the window over one row.
- **Card draws by offset, not `ORDER BY RANDOM()`**, which would scan the whole
  pool every turn.
- **Keyset pagination** on the event log, which stays flat as sessions pile up.
- **Atomic `F()` updates** for points and XP, so concurrent awards can't lose
  one to a stale read.
- **A read replica is one env var** (`DATABASE_REPLICA_URL`). The router in
  `apps/common/db.py` keeps `games` pinned to the primary, because replication
  lag inside a turn would resurrect stale state.

### Scaling shape

Turn-based play is not chatty: a table of four generates a handful of messages a
minute, and each one is a small JSON frame. The limits you will meet in order:

1. **Concurrent sockets per process.** Each is an idle coroutine. A worker
   handles thousands; `--workers 4` on a small instance is tens of thousands.
   Scale horizontally — Redis already carries frames between processes.
2. **Redis channel-layer throughput.** One publish per mutation. Well past
   anything a per-family game will produce.
3. **Postgres write throughput.** Every turn is a short locked transaction plus
   one event insert. Partition or archive `games_gameevent` when history grows.

Sticky sessions are **not** required: any process can serve any socket.

---

## Production

`config.settings.prod` refuses to start on a weak `DJANGO_SECRET_KEY`, a
missing `DATABASE_URL`, or `DJANGO_ALLOWED_HOSTS=*`. Failing at boot beats
discovering it later.

Also enabled there: HSTS, SSL redirect behind `X-Forwarded-Proto`, secure
cookies, JSON logs, and Sentry when `SENTRY_DSN` is set.

**Checklist**

1. `DJANGO_SETTINGS_MODULE=config.settings.prod`
2. Set `DJANGO_SECRET_KEY` (32+ random chars), `DJANGO_ALLOWED_HOSTS`,
   `DATABASE_URL`, `REDIS_URL`, `PUBLIC_BASE_URL`.
3. `python manage.py migrate && python manage.py seed_content`
4. Serve `config.asgi:application` with gunicorn + `uvicorn_worker.UvicornWorker`
   (see the `Dockerfile`).
5. Point the load balancer's health check at `/readyz`, and its liveness probe
   at `/healthz`. `/readyz` checks the database; `/healthz` deliberately checks
   nothing, so a database blip doesn't get healthy pods restarted.
6. Make sure the proxy forwards `Upgrade`/`Connection` on `/ws/` and doesn't
   time out idle sockets (`deploy/nginx.conf` shows both).
7. Move `MEDIA_ROOT` to object storage — uploaded card art is on local disk by
   default, which does not survive a redeploy or work across replicas.

### Rate limits

Off in development, on elsewhere: `auth` 20/min, `register` 10/hour, `join`
30/min, turn actions 120/min, other writes 60/min — all `THROTTLE_*` env vars.
Websockets are limited per connection (30 actions / 10s).

---

## Seeded content

`python manage.py seed_content` creates the six built-in decks, ten cards and
five badges from the app's own mock fixtures, artwork references included, so
flipping `EXPO_PUBLIC_USE_MOCKS=false` shows the same library rather than an
empty Deck Master. It is idempotent — safe on every deploy.

Art references are stored as strings: `asset://<key>` resolves to artwork
bundled in the app, and an `https://` URL is handled identically by
`artSource()`, so real uploads slot in with no client change.

---

## One client change is needed

Everything else in `src/` works against this backend untouched. The exception is
card art.

`CreateCardScreen` sends the image picker's local URI (`file:///…`) as
`artUrl`. That URI only means something on the device that picked it, so storing
it would look like success and then show a broken image on every other phone at
the table. The API rejects it with a message naming the fix, and provides the
endpoint that does work:

```ts
// Upload first, then send the URL the server returns.
const form = new FormData();
form.append("file", { uri: artUri, name: "art.jpg", type: "image/jpeg" } as any);
const { data } = await apiClient.post<{ url: string }>("/uploads/card-art/", form, {
  headers: { "Content-Type": "multipart/form-data" },
});
await createCard.mutateAsync({ ...rest, artUrl: data.url });
```

Two optional client additions, both additive:

- A `useSessionSocket(id)` hook that opens the websocket and writes each frame
  into the React Query caches (three lines, shown under **Realtime** above),
  dropping frames whose `version` isn't newer. Until it exists the app's
  existing polling keeps working.
- `refetchInterval` on `useGameState` — the board currently has none and relies
  on mutation responses, which is fine with a socket and not without one.
