from django.contrib.auth import views as auth_views
from django.urls import include, path

from . import (views, views_followup, views_photo, views_prefs, views_privacy, views_pwa, views_recovery,
               views_schools)
from .forms import ThrottledAuthenticationForm

urlpatterns = [
    path("", views.home, name="home"),
    # PWA: app instalável no celular + página offline (recursos públicos, servidos da raiz).
    path("manifest.webmanifest", views_pwa.manifest, name="manifest"),
    path("sw.js", views_pwa.service_worker, name="service_worker"),
    path("offline/", views_pwa.offline, name="offline"),
    path("busca/", views.global_search, name="global_search"),
    path("ajuda/", views.help_page, name="help"),
    path("privacidade/", views_privacy.privacy_page, name="privacy"),
    path("privacidade/editar/", views_privacy.privacy_edit, name="privacy_edit"),
    path("preferencias/", views_prefs.save_preferences, name="save_preferences"),
    path("falhas-tecnicas/", views.error_log, name="error_log"),
    path("minha-foto/", views_photo.my_photo, name="my_photo"),
    path("pendencias/", views_photo.pending_center, name="pending_center"),
    path("pendencias/acompanhadas/", views_followup.follow_up_list, name="follow_up_list"),
    path("pendencias/acompanhadas/nova/", views_followup.follow_up_create, name="follow_up_create"),
    path("pendencias/acompanhadas/<int:pk>/", views_followup.follow_up_detail, name="follow_up_detail"),
    path("fotografias/pendentes/", views_photo.photo_pending, name="photo_pending"),
    path("fotografias/cobrar/", views_photo.photo_remind, name="photo_remind"),
    path("fotografias/dispensas/nova/", views_photo.photo_exception_create, name="photo_exception_create"),
    path("fotografias/dispensas/<int:pk>/revogar/", views_photo.photo_exception_revoke,
         name="photo_exception_revoke"),
    path("cadastro/", views.signup, name="signup"),
    path("cadastro/convite/", views_schools.invite_signup, name="invite_signup"),
    path("escolas/", views_schools.school_list, name="school_list"),
    path("escolas/nova/", views_schools.school_create, name="school_create"),
    path("escolas/<int:school_id>/editar/", views_schools.school_edit, name="school_edit"),
    path("escolas/<int:school_id>/trabalhar/", views_schools.school_switch, name="school_switch"),
    path("escolas/<int:school_id>/equipe/", views_schools.school_team, name="school_team"),
    path("escolas/<int:school_id>/convites/novo/", views_schools.invite_create, name="invite_create"),
    path("equipe/", views_schools.my_team, name="my_team"),
    path("convites/<int:invite_id>/cancelar/", views_schools.invite_revoke, name="invite_revoke"),
    path("convites/cadastros/<int:signup_id>/decidir/", views_schools.signup_decide, name="signup_decide"),
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
    path("senha/codigos/", views_recovery.recovery_codes, name="recovery_codes"),
    path("senha/recuperar/", views_recovery.password_recover, name="password_recover"),
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