from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("paineis/", views.institutional_dashboard, name="institutional_dashboard"),
    path(
        "paineis/secretaria/",
        views.secretaria_panel,
        name="secretaria_panel",
    ),
    path(
        "paineis/estudante/<int:student_id>/",
        views.student_dashboard,
        name="student_dashboard",
    ),
    path(
        "paineis/estudante/<int:student_id>/simulador/",
        views.student_simulator,
        name="student_simulator",
    ),
    path(
        "paineis/turma/<int:class_group_id>/",
        views.class_dashboard,
        name="class_dashboard",
    ),
    path(
        "paineis/estudante/<int:student_id>/exportar.<str:fmt>",
        views.student_export,
        name="student_export",
    ),
    path("paineis/metodologia/", views.methodology, name="methodology"),
    path("paineis/turma/<int:class_group_id>/exportar.<str:fmt>", views.class_export, name="class_export"),
    path("paineis/disciplina/", views.subject_dashboard, name="subject_index"),
    path("paineis/disciplina/<int:subject_id>/", views.subject_dashboard, name="subject_dashboard"),
    path("paineis/disciplina/<int:subject_id>/exportar.<str:fmt>", views.subject_export, name="subject_export"),
    path("paineis/professor/", views.teacher_dashboard, name="teacher_dashboard"),
    path("paineis/qualidade-dos-dados/", views.data_quality_dashboard, name="data_quality"),
    path("paineis/metas/", views.goals, name="goals"),
    path("paineis/metas/nova/", views.goal_form, name="goal_create"),
    path("paineis/metas/<int:pk>/", views.goal_form, name="goal_edit"),
    path("relatorios/", views.report_hub, name="report_hub"),
    path("relatorios/<slug:slug>/", views.report_detail, name="report_detail"),
    path("relatorios/<slug:slug>/exportar.csv", views.report_csv, name="report_csv"),
]
