import logging
import threading

from django.db.models.signals import post_save
from django.dispatch import receiver

from .emails import send_welcome_email
from .models import User

logger = logging.getLogger(__name__)


def _send_welcome_async(user_id: str) -> None:
    try:
        user = User.objects.get(pk=user_id)
        send_welcome_email(user)
    except Exception:
        logger.exception("Failed to send welcome email to user %s", user_id)


@receiver(post_save, sender=User)
def on_user_created(sender, instance, created, **kwargs):
    if not created:
        return
    threading.Thread(target=_send_welcome_async, args=(str(instance.pk),), daemon=True).start()
