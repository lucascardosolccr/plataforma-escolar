from django.urls import path

from . import views_office as v

app_name = "office"

urlpatterns = [
    path("horarios-de-atendimento/", v.office_list, name="list"),
    path("horarios-de-atendimento/novo/", v.office_form, name="create"),
    path("horarios-de-atendimento/<int:pk>/", v.office_detail, name="detail"),
    path("horarios-de-atendimento/<int:pk>/editar/", v.office_form, name="edit"),
    path("horarios-de-atendimento/<int:pk>/marcar/", v.office_book, name="book"),
    path("horarios-de-atendimento/<int:pk>/fechar/", v.office_toggle, name="toggle"),
    path("horarios-de-atendimento/<int:pk>/apagar/", v.office_delete, name="delete"),
    path("horarios-de-atendimento/horario/<int:slot_pk>/desmarcar/", v.office_release, name="release"),
]
