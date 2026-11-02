from django.urls import path

from . import views, views_library

app_name = "study"

P = "conteudos-da-prova/"
urlpatterns = [
    path(P, views.guide_list, name="list"),
    path(P + "novo/", views.guide_create, name="create"),
    path(P + "<int:pk>/", views.guide_detail, name="detail"),
    path(P + "<int:pk>/editar/", views.guide_edit, name="edit"),
    path(P + "<int:pk>/reutilizar/", views.guide_reuse, name="reuse"),
    path(P + "<int:pk>/situacao/<str:action>/", views.guide_status, name="status"),
    path(P + "<int:pk>/topicos/novo/", views.topic_form, name="topic_add"),
    path(P + "<int:pk>/topicos/<int:topic_id>/", views.topic_form, name="topic_edit"),
    path(P + "<int:pk>/topicos/<int:topic_id>/retirar/", views.topic_delete, name="topic_delete"),
    path(P + "<int:pk>/topicos/<int:topic_id>/como-estou/", views.topic_check, name="topic_check"),
    path(P + "<int:pk>/materiais/novo/", views.material_form, name="material_add"),
    path(P + "<int:pk>/materiais/<int:material_id>/", views.material_form, name="material_edit"),
    path(P + "<int:pk>/materiais/<int:material_id>/substituir/", views.material_form, {"replace": True},
         name="material_replace"),
    path(P + "<int:pk>/materiais/<int:material_id>/retirar/", views.material_remove, name="material_remove"),
    path(P + "<int:pk>/materiais/<int:material_id>/arquivo/", views.material_file, name="material_file"),
    path(P + "<int:pk>/materiais/<int:material_id>/link-quebrado/", views.material_report, name="material_report"),
    path(P + "<int:pk>/materiais/<int:material_id>/link-resolvido/", views.material_report_clear,
         name="material_report_clear"),
    path(P + "<int:pk>/duvidas/", views.question_add, name="question_add"),
    path(P + "<int:pk>/duvidas/<int:question_id>/responder/", views.question_answer, name="question_answer"),
    path(P + "<int:pk>/estudante/<int:student_id>/", views.student_plan, name="student_plan"),
    path("biblioteca/", views_library.library, name="library"),
    path("biblioteca/<int:material_id>/arquivo/", views_library.library_file, name="library_file"),
    path("biblioteca/<int:material_id>/favorito/", views_library.library_favorite, name="library_favorite"),
    path("biblioteca/<int:material_id>/usar/", views_library.library_use, name="library_use"),
]
