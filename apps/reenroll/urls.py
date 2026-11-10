from django.urls import path

from . import views

app_name = "reenroll"

urlpatterns = [
    path("rematricula/", views.index, name="index"),
    path("rematricula/nova/", views.campaign_form, name="create"),
    path("rematricula/<int:pk>/", views.detail, name="detail"),
    path("rematricula/<int:pk>/editar/", views.campaign_form, name="edit"),
    path("rematricula/<int:pk>/responder/", views.answer, name="answer"),
    path("rematricula/<int:pk>/balcao/<int:student_id>/", views.answer_in_person, name="in_person"),
    path("rematricula/<int:pk>/lembrar/", views.remind_now, name="remind"),
    path("rematricula/<int:pk>/encerrar/", views.toggle_closed, name="toggle"),
    path("rematricula/<int:pk>/exportar/", views.export_csv, name="export"),
    path("rematricula/resposta/<int:pk>/cadastro-atualizado/", views.data_done, name="data_done"),
]
