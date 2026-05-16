from django.db import transaction
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .notifications import send_welcome_email


@receiver(post_save, sender=User)
def user_created_send_welcome_email(sender, instance, created, **kwargs):
    if not created:
        return
    if not getattr(settings, 'WELCOME_EMAIL_ENABLED', True):
        return
    if not instance.email:
        return
    transaction.on_commit(lambda user=instance: send_welcome_email(user))