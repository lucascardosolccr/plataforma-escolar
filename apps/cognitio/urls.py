from django.urls import path

from . import views, views_evidence

app_name = "cognitio"

urlpatterns = [
    path("cognitio/", views.home, name="home"),
    path("cognitio/escala/", views.scale_settings, name="scale"),
    path("cognitio/estudante/<int:student_id>/", views.student_map, name="student_map"),
    path("cognitio/turma/<int:class_id>/", views.class_view, name="class_view"),
    path("cognitio/turma/<int:class_id>/disciplina/<int:subject_id>/observacao/", views_evidence.observation_create,
         name="observation_create"),
    path("cognitio/avaliacao/<int:evaluation_id>/questoes/", views_evidence.questions, name="questions"),
    path("cognitio/avaliacao/<int:evaluation_id>/resultados/", views_evidence.responses, name="responses"),
]
