from django.urls import path

from . import views, views_report_cards, views_spc

app_name = "analytics"

urlpatterns = [
    path("paineis/", views.institutional_dashboard, name="institutional_dashboard"),
    path("paineis/frequencia-semanal/", views_spc.attendance_control, name="attendance_control"),
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
    path("paineis/turma/<int:class_group_id>/boletins/", views_report_cards.class_report_cards,
         name="class_report_cards"),
    path(
        "paineis/estudante/<int:student_id>/exportar.<str:fmt>",
        views.student_export,
        name="student_export",
    ),
    path("paineis/estudante/<int:student_id>/dados.json", views.student_data, name="student_data"),
    path("paineis/turma/<int:class_group_id>/dados.json", views.class_data, name="class_data"),
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
