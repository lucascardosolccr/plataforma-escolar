from django.urls import path

from . import views

app_name = "paperwork"

urlpatterns = [
    path("documentos-da-matricula/", views.index, name="index"),
    path("documentos-da-matricula/turma/<int:class_id>/salvar/", views.save_class, name="save_class"),
    path("documentos-da-matricula/estudante/<int:student_id>/", views.student_page, name="student"),
    path("documentos-da-matricula/lista/", views.settings_page, name="settings"),
    path("documentos-da-matricula/lista/<int:pk>/", views.settings_page, name="settings_edit"),
    path("documentos-da-matricula/lembrar/", views.remind, name="remind"),
    path("documentos-da-matricula/pendentes.csv", views.export_csv, name="export"),
]
