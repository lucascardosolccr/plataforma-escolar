from django.contrib.auth import views as auth_views
from django.urls import include, path

from . import views, views_photo
from .forms import ThrottledAuthenticationForm

urlpatterns = [
    path("", views.home, name="home"),
    path("busca/", views.global_search, name="global_search"),
    path("ajuda/", views.help_page, name="help"),
    path("minha-foto/", views_photo.my_photo, name="my_photo"),
    path("fotografias/pendentes/", views_photo.photo_pending, name="photo_pending"),
    path("fotografias/cobrar/", views_photo.photo_remind, name="photo_remind"),
    path("fotografias/dispensas/nova/", views_photo.photo_exception_create, name="photo_exception_create"),
    path("fotografias/dispensas/<int:pk>/revogar/", views_photo.photo_exception_revoke,
         name="photo_exception_revoke"),
    path("cadastro/", views.signup, name="signup"),
    path(
        "login/",
        auth_views.LoginView.as_view(redirect_authenticated_user=True,
                                     authentication_form=ThrottledAuthenticationForm),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "senha/trocar/",
        views.ForcedPasswordChangeView.as_view(),
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
                path("<int:user_id>/foto/", views_photo.user_photo, name="user_photo"),
                path("<int:user_id>/foto/enviar/", views_photo.staff_photo_upload, name="staff_photo_upload"),
                path(
                    "<int:user_id>/redefinir-senha/",
                    views.password_reset_user,
                    name="password_reset_user",
                ),
            ]
        ),
    ),
]