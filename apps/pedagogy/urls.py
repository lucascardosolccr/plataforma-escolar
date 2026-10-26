from django.urls import path

from . import views

app_name = "pedagogy"

urlpatterns = [
    path("avaliacoes/", views.evaluation_list, name="evaluation_list"),
    path("avaliacoes/nova/", views.evaluation_create, name="evaluation_create"),
    path("avaliacoes/<int:pk>/editar/", views.evaluation_edit, name="evaluation_edit"),
    path("avaliacoes/<int:pk>/lancar/", views.evaluation_grade, name="evaluation_grade"),
    path("avaliacoes/<int:pk>/publicar/", views.evaluation_publish, name="evaluation_publish"),
    path("atividades/", views.activity_list, name="activity_list"),
    path("atividades/nova/", views.activity_create, name="activity_create"),
    path("atividades/<int:pk>/editar/", views.activity_edit, name="activity_edit"),
    path(
        "atividades/<int:pk>/entregas/",
        views.activity_submissions,
        name="activity_submissions",
    ),
    path("frequencia/", views.attendance_list, name="attendance_list"),
    path(
        "frequencia/turma/<int:class_group_id>/",
        views.attendance_class,
        name="attendance_class",
    ),
    path(
        "frequencia/turma/<int:class_group_id>/registrar/",
        views.attendance_register,
        name="attendance_register",
    ),
    path("ocorrencias/", views.occurrence_list, name="occurrence_list"),
    path("ocorrencias/nova/", views.occurrence_create, name="occurrence_create"),
    path("ocorrencias/<int:pk>/", views.occurrence_detail, name="occurrence_detail"),
    path("observacoes/", views.observation_list, name="observation_list"),
    path("observacoes/nova/", views.observation_create, name="observation_create"),
    path("observacoes/<int:pk>/editar/", views.observation_edit, name="observation_edit"),
    path("planos/", views.plan_list, name="plan_list"),
    path("planos/novo/", views.plan_create, name="plan_create"),
    path("planos/<int:pk>/", views.plan_detail, name="plan_detail"),
    path("justificativas/", views.justification_list, name="justification_list"),
    path("justificativas/nova/", views.justification_create, name="justification_create"),
    path(
        "justificativas/<int:pk>/<str:decision>/",
        views.justification_resolve,
        name="justification_resolve",
    ),
    path("config/", views.config_edit, name="config_edit"),
    path(
        "config/regra/<int:subject_id>/",
        views.academic_rule_edit,
        name="academic_rule_edit",
    ),
]