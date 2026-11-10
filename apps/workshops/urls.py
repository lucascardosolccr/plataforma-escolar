from django.urls import path

from . import views

app_name = "workshops"

urlpatterns = [
    path("oficinas/", views.index, name="index"),
    path("oficinas/nova/", views.workshop_form, name="create"),
    path("oficinas/<int:pk>/", views.detail, name="detail"),
    path("oficinas/<int:pk>/editar/", views.workshop_form, name="edit"),
    path("oficinas/<int:pk>/publicar/", views.publish, name="publish"),
    path("oficinas/<int:pk>/encerrar/", views.toggle, name="toggle"),
    path("oficinas/<int:pk>/inscrever/", views.sign_up, name="sign_up"),
    path("oficinas/<int:pk>/inscritos.csv", views.export_csv, name="export"),
    path("oficinas/inscricao/<int:signup_pk>/cancelar/", views.cancel, name="cancel"),
]
