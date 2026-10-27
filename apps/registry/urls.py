from django.urls import path

from . import views

urlpatterns = [
    path("estudantes/", views.student_list, name="student_list"),
    path("estudantes/novo/", views.student_create, name="student_create"),
    path("estudantes/<int:student_id>/", views.student_detail, name="student_detail"),
    path("estudantes/<int:student_id>/editar/", views.student_edit, name="student_edit"),
    path("estudantes/<int:student_id>/foto/", views.student_photo, name="student_photo"),
    path(
        "estudantes/<int:student_id>/acesso/",
        views.student_account_create,
        name="student_account_create",
    ),
    path("responsaveis/", views.guardian_list, name="guardian_list"),
    path(
        "responsaveis/<int:user_id>/",
        views.guardian_profile,
        name="guardian_profile",
    ),
    path("responsaveis/<int:user_id>/foto/", views.guardian_photo, name="guardian_photo"),
    path("meus-filhos/", views.my_children, name="my_children"),
    path("vinculos/", views.link_list, name="link_list"),
    path("vinculos/solicitar/", views.link_request, name="link_request"),
    path("vinculos/novo/", views.link_create, name="link_create"),
    path("vinculos/<int:link_id>/aprovar/", views.link_approve, name="link_approve"),
    path("vinculos/<int:link_id>/rejeitar/", views.link_reject, name="link_reject"),
    path("matriculas/", views.enrollment_list, name="enrollment_list"),
    path("matriculas/nova/", views.enrollment_create, name="enrollment_create"),
    path(
        "matriculas/<int:enrollment_id>/editar/",
        views.enrollment_edit,
        name="enrollment_edit",
    ),
]