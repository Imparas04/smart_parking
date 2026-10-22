from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_profile(sender, instance, created, **kwargs):
    profile, _ = Profile.objects.get_or_create(user=instance)
    if instance.is_superuser and profile.role != Profile.ROLE_ADMIN:
        profile.role = Profile.ROLE_ADMIN
        profile.save(update_fields=['role', 'updated_at'])
