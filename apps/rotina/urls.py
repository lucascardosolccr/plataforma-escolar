from django.urls import path

from . import views

app_name = "rotina"

urlpatterns = [
    path("cardapio/", views.menu_view, name="menu"),
    path("cardapio/editar/", views.menu_edit, name="menu_edit"),
    path("cardapio/copiar-semana/", views.menu_copy_week, name="menu_copy_week"),
    path("horarios/", views.schedule_index, name="schedule_index"),
    path("horarios/meus/", views.schedule_teacher, name="schedule_teacher"),
    path("horarios/turma/<int:class_id>/", views.schedule_class, name="schedule_class"),
    path("horarios/aula/<int:pk>/retirar/", views.schedule_delete, name="schedule_delete"),
]
