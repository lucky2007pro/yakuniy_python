from django.conf import settings
from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdminTokenOrReadOnly(BasePermission):
    """
    Allows read for everyone, but write operations only when the request
    carries the configured admin token (X-Admin-Token header) or the user
    is a Django staff user.
    """

    message = 'Admin token is required for this operation.'

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True

        if request.user and request.user.is_staff:
            return True

        token = request.headers.get('X-Admin-Token', '')
        return bool(token) and token == getattr(settings, 'ADMIN_API_TOKEN', '')


class IsAdminToken(BasePermission):
    """Strict admin-only permission via token."""

    message = 'Admin token is required.'

    def has_permission(self, request, view):
        if request.user and request.user.is_staff:
            return True
        token = request.headers.get('X-Admin-Token', '')
        return bool(token) and token == getattr(settings, 'ADMIN_API_TOKEN', '')
