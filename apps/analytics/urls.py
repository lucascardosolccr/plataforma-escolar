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
    path("relatorios/", views.report_hub, name="report_hub"),
    path("relatorios/<slug:slug>/", views.report_detail, name="report_detail"),
    path("relatorios/<slug:slug>/exportar.csv", views.report_csv, name="report_csv"),
]
