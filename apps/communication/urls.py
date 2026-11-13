from django.urls import path

from . import views, views_authorizations, views_polls

app_name = "communication"

urlpatterns = [
    path("notificacoes/", views.notification_list, name="notification_list"),
    path("notificacoes/preferencias/", views.notification_preferences, name="notification_preferences"),
    path("notificacoes/regras/", views.notification_rules, name="notification_rules"),
    path(
        "notificacoes/<int:pk>/abrir/",
        views.notification_read,
        name="notification_read",
    ),
    path(
        "notificacoes/marcar-selecionadas/",
        views.notification_read_selected,
        name="notification_read_selected",
    ),
    path(
        "notificacoes/marcar-todas/",
        views.notification_read_all,
        name="notification_read_all",
    ),
    path("legibilidade/", views.readability_check, name="readability_check"),
    path("mensagens/", views.thread_list, name="thread_list"),
    path("mensagens/nova/", views.thread_create, name="thread_create"),
    path("mensagens/<int:pk>/", views.thread_detail, name="thread_detail"),
    path("mensagens/anexo/<int:pk>/", views.message_attachment, name="message_attachment"),
    path("comunicados/", views.announcement_list, name="announcement_list"),
    path("comunicados/novo/", views.announcement_create, name="announcement_create"),
    path("comunicados/<int:pk>/", views.announcement_detail, name="announcement_detail"),
    path("autorizacoes/", views_authorizations.authorization_list, name="authorization_list"),
    path("autorizacoes/nova/", views_authorizations.authorization_create, name="authorization_create"),
    path("autorizacoes/<int:pk>/", views_authorizations.authorization_detail, name="authorization_detail"),
    path("autorizacoes/<int:pk>/responder/", views_authorizations.authorization_answer, name="authorization_answer"),
    path("autorizacoes/<int:pk>/assinar/<int:student_id>/", views_authorizations.authorization_sign,
         name="authorization_sign"),
    path("autorizacoes/<int:pk>/lembrar/", views_authorizations.authorization_remind, name="authorization_remind"),
    path("autorizacoes/comprovante/<str:code>/", views_authorizations.authorization_receipt,
         name="authorization_receipt"),
    path("autorizacoes/verificar/", views_authorizations.authorization_verify, name="authorization_verify"),
    path("autorizacoes/fotos/", views_authorizations.authorization_images, name="authorization_images"),
    path("autorizacoes/<int:pk>/<str:action>/", views_authorizations.authorization_status,
         name="authorization_status"),
    path("consultas/", views_polls.poll_list, name="poll_list"),
    path("consultas/nova/", views_polls.poll_create, name="poll_create"),
    path("consultas/<int:pk>/", views_polls.poll_detail, name="poll_detail"),
    path("consultas/<int:pk>/votar/", views_polls.poll_vote, name="poll_vote"),
    path("consultas/<int:pk>/encerrar/", views_polls.poll_close, name="poll_close"),
    path("solicitacoes/", views.request_list, name="request_list"),
    path("solicitacoes/nova/", views.request_create, name="request_create"),
    path("solicitacoes/<int:pk>/", views.request_detail, name="request_detail"),
]