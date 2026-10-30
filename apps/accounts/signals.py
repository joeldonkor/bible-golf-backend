import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .emails import send_welcome_email
from .models import User

logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def on_user_created(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        send_welcome_email(instance)
    except Exception:
        logger.exception("Failed to send welcome email to %s", instance.email)
