from functools import wraps
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from .models import Profile
from .services import get_tracker
def tracker_user_for(request):
    if not request.user.is_authenticated:
        return None
    if hasattr(request, "_tracker_user"):
        return request._tracker_user
    tracker = get_tracker()
    profile = Profile.objects.filter(user=request.user).first()
    user = tracker.users.get(profile.tracker_user_id) if profile else None
    if user is None and request.user.is_superuser:
        name = request.user.get_full_name() or request.user.username
        user = tracker.register_web_user(name, role="admin")
        Profile.objects.update_or_create(user=request.user, defaults={"tracker_user_id": user.id})
    request._tracker_user = user
    return user
def employee_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = tracker_user_for(request)
        if user is None:
            logout(request)
            messages.error(request, "Учётная запись не связана с сотрудником трекера.")
            return redirect("login")
        return view(request, user, *args, **kwargs)
    return wrapper
def admin_required(view):
    @employee_required
    @wraps(view)
    def wrapper(request, user, *args, **kwargs):
        if not user.is_admin:
            messages.error(request, "Раздел доступен только администраторам.")
            return redirect("dashboard")
        return view(request, user, *args, **kwargs)
    return wrapper
