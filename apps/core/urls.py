from django.contrib.auth import views as auth_views
from django.urls import include, path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("cadastro/", views.signup, name="signup"),
    path(
        "login/",
        auth_views.LoginView.as_view(redirect_authenticated_user=True),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "senha/trocar/",
        auth_views.PasswordChangeView.as_view(),
        name="password_change",
    ),
    path(
        "senha/trocar/feito/",
        auth_views.PasswordChangeDoneView.as_view(),
        name="password_change_done",
    ),
    path(
        "usuarios/",
        include(
            [
                path("", views.user_list, name="user_list"),
                path("novo/", views.user_create, name="user_create"),
                path("<int:user_id>/", views.user_detail, name="user_detail"),
            ]
        ),
    ),
]