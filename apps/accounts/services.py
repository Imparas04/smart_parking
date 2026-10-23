from django.core.exceptions import ValidationError

from .models import Profile


def _guard(actor, target):
    # The actor is an active admin and cannot be the target, so at least one admin always remains.
    if actor.pk == target.pk:
        raise ValidationError('You cannot change your own account here.')
    if target.is_superuser:
        raise ValidationError('Superuser accounts are managed in Django admin.')


def set_active(actor, target, active):
    _guard(actor, target)
    target.is_active = bool(active)
    target.save(update_fields=['is_active'])
    return target


def set_role(actor, target, role):
    _guard(actor, target)
    if role not in dict(Profile.ROLE_CHOICES):
        raise ValidationError('Invalid role.')
    target.profile.role = role
    target.profile.save(update_fields=['role', 'updated_at'])
    return target
