"""Abstract base models shared by every app."""

import uuid

from django.db import models


class UUIDModel(models.Model):
    """
    UUID primary key.

    The mobile client treats every `id` as an opaque string, and UUIDs keep
    sequential integers (and the row counts they leak) off the wire.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BaseModel(UUIDModel, TimeStampedModel):
    class Meta:
        abstract = True
