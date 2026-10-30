from django.urls import path

from . import views, views_permissions

urlpatterns = [
    path("turmas/", views.class_group_list, name="class_group_list"),
    path("turmas/nova/", views.class_group_create, name="class_group_create"),
    path(
        "turmas/<int:class_group_id>/editar/",
        views.class_group_edit,
        name="class_group_edit",
    ),
    path("disciplinas/", views.subject_list, name="subject_list"),
    path("disciplinas/nova/", views.subject_create, name="subject_create"),
    path(
        "disciplinas/<int:subject_id>/editar/",
        views.subject_edit,
        name="subject_edit",
    ),
    path("anos-letivos/", views.school_year_list, name="school_year_list"),
    path("anos-letivos/novo/", views.school_year_create, name="school_year_create"),
    path(
        "anos-letivos/<int:year_id>/editar/",
        views.school_year_edit,
        name="school_year_edit",
    ),
    path("atribuicoes/", views.assignment_list, name="assignment_list"),
    path("atribuicoes/nova/", views.assignment_create, name="assignment_create"),
    path("atribuicoes/permissoes/", views_permissions.permission_list, name="teacher_permissions"),
    path("atribuicoes/permissoes/<int:pk>/revogar/", views_permissions.permission_revoke,
         name="teacher_permission_revoke"),
    path(
        "atribuicoes/<int:assignment_id>/remover/",
        views.assignment_delete,
        name="assignment_delete",
    ),
    path("minhas-turmas/", views.my_classrooms, name="my_classrooms"),
]