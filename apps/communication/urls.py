from django.urls import path

from . import views

app_name = "communication"

urlpatterns = [
    path("notificacoes/", views.notification_list, name="notification_list"),
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
    path("mensagens/", views.thread_list, name="thread_list"),
    path("mensagens/nova/", views.thread_create, name="thread_create"),
    path("mensagens/<int:pk>/", views.thread_detail, name="thread_detail"),
    path("comunicados/", views.announcement_list, name="announcement_list"),
    path("comunicados/novo/", views.announcement_create, name="announcement_create"),
    path("comunicados/<int:pk>/", views.announcement_detail, name="announcement_detail"),
    path("solicitacoes/", views.request_list, name="request_list"),
    path("solicitacoes/nova/", views.request_create, name="request_create"),
    path("solicitacoes/<int:pk>/", views.request_detail, name="request_detail"),
]