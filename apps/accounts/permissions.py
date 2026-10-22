from rest_framework.permissions import BasePermission


def is_admin(user):
    if not user.is_authenticated:
        return False
    profile = getattr(user, 'profile', None)
    return user.is_superuser or bool(profile and profile.role == 'admin')


class IsAdminRole(BasePermission):
    message = 'Admin role required.'

    def has_permission(self, request, view):
        return is_admin(request.user)
