from rest_framework.permissions import BasePermission

from .models import UserProfile


class IsAdminUser(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        profile = getattr(user, 'profile', None)
        return profile is not None and profile.role == UserProfile.Role.ADMIN
