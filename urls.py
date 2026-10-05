from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import LoginForm

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(authentication_form=LoginForm,
                                                redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", views.register, name="register"),
    path("password/", auth_views.PasswordChangeView.as_view(
        template_name="cabinet/password_change.html", success_url="/profile/"),
         name="password_change"),

    path("work/", views.dashboard, name="dashboard"),
    path("work/<str:action>/", views.session_action, name="session_action"),
    path("api/state/", views.api_state, name="api_state"),
    path("api/checks/<int:check_id>/answer/", views.api_answer, name="api_answer"),
    path("stats/", views.stats, name="stats"),
    path("sessions/<int:session_id>/", views.session_detail, name="session_detail"),
    path("profile/", views.profile, name="profile"),
    path("live/", views.live, name="live"),
    path("team/", views.team, name="team"),
    path("team/<int:user_id>/", views.employee, name="employee"),
    path("violations/", views.violations, name="violations"),
    path("projects/", views.projects, name="projects"),
    path("users/", views.users, name="users"),
    path("export.csv", views.export_csv, name="export_csv"),
]