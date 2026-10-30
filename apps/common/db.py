"""Database helpers: read-replica routing and portable advisory locking."""

from contextlib import contextmanager

from django.db import connections, router, transaction

# Models whose reads must never hit a replica: anything read inside a
# read-modify-write turn, where replication lag would resurrect stale state.
STRICT_PRIMARY_APPS = frozenset({"games", "token_blacklist"})


class ReadReplicaRouter:
    """
    Sends read traffic to `replica` when one is configured.

    Leaderboards and deck browsing are the bulk of reads and tolerate a second
    of lag; game state does not, so `games` is pinned to the primary.
    """

    def db_for_read(self, model, **hints):
        if model._meta.app_label in STRICT_PRIMARY_APPS:
            return "default"
        return "replica" if "replica" in connections else "default"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, **hints):
        return db == "default"


@contextmanager
def locked(queryset, pk):
    """
    Fetch one row under a row-level write lock inside a transaction.

    Every turn action is a read-modify-write on the session; without this, two
    players tapping "Take Swing" at the same instant both read the same state
    and one write silently wins. SQLite has no `SELECT ... FOR UPDATE`, but its
    writer lock already serialises the transaction, so the fallback is correct.
    """
    with transaction.atomic():
        db = router.db_for_write(queryset.model)
        supports_select_for_update = connections[db].features.has_select_for_update
        qs = queryset.select_for_update() if supports_select_for_update else queryset
        yield qs.get(pk=pk)
