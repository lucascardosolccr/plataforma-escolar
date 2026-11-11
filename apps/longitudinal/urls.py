from django.urls import path

from . import views

app_name = "longitudinal"

urlpatterns = [
    path("trajetoria-escolar/", views.index, name="index"),
    path("trajetoria-escolar/estudante/<int:student_id>/", views.student_page, name="student"),
    path("trajetoria-escolar/estudante/<int:student_id>/ano-anterior/", views.prior_form, name="prior_create"),
    path("trajetoria-escolar/estudante/<int:student_id>/ano-anterior/<int:pk>/", views.prior_form, name="prior_edit"),
    path("trajetoria-escolar/ano-anterior/<int:pk>/excluir/", views.prior_delete, name="prior_delete"),
    path("trajetoria-escolar/importar/", views.import_view, name="import"),
    path("trajetoria-escolar/importar/modelo.csv", views.import_template, name="import_template"),
    path("trajetoria-escolar/resultados/", views.results, name="results"),
    path("trajetoria-escolar/resultados/turma/<int:class_id>/", views.results_class, name="results_class"),
    path("trajetoria-escolar/previsao/", views.model_page, name="model"),
    path("trajetoria-escolar/sinais.csv", views.export_csv, name="export"),
]
