from django.urls import path

from . import views

app_name = "inclusion"

urlpatterns = [
    path("apoio/", views.overview, name="overview"),
    path("apoio/orientacoes/", views.guidance, name="guidance"),
    path("apoio/painel/", views.panel, name="panel"),
    path("apoio/configuracoes/", views.settings_view, name="settings"),
    path("apoio/retencao/", views.retention, name="retention"),
    path("apoio/estudante/<int:student_id>/", views.case_detail, name="case_detail"),
    path("apoio/estudante/<int:student_id>/abrir/", views.student_entry, name="student_entry"),
    path("apoio/estudante/<int:student_id>/informar/", views.declare, name="declare"),
    path("apoio/estudante/<int:student_id>/documento/", views.document_upload, name="document_upload"),
    path("apoio/estudante/<int:student_id>/complementacao/", views.request_create, name="request_create"),
    path("apoio/estudante/<int:student_id>/analise/", views.case_analysis, name="case_analysis"),
    path("apoio/estudante/<int:student_id>/necessidade/", views.need_edit, name="need_create"),
    path("apoio/estudante/<int:student_id>/necessidade/<int:pk>/", views.need_edit, name="need_edit"),
    path("apoio/estudante/<int:student_id>/plano/", views.plan_edit, name="plan_create"),
    path("apoio/estudante/<int:student_id>/plano/<int:pk>/", views.plan_edit, name="plan_edit"),
    path("apoio/estudante/<int:student_id>/plano/<int:pk>/registro/", views.plan_review, name="plan_review"),
    path("apoio/documento/<uuid:public_id>/", views.document_download, name="document_download"),
    path("apoio/documento/<uuid:public_id>/analise/", views.document_review, name="document_review"),
    path("apoio/complementacao/<int:pk>/responder/", views.request_respond, name="request_respond"),
    path("apoio/complementacao/<int:pk>/encerrar/", views.request_close, name="request_close"),
]
