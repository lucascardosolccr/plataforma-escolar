from django.urls import path

from . import views

app_name = "printing"

urlpatterns = [
    path("impressoes/", views.my_requests, name="mine"),
    path("impressoes/nova/", views.request_form, name="create"),
    path("impressoes/fila/", views.queue, name="queue"),
    path("impressoes/<int:pk>/", views.detail, name="detail"),
    path("impressoes/<int:pk>/editar/", views.request_form, name="edit"),
    path("impressoes/<int:pk>/acao/", views.act, name="act"),
    path("impressoes/<int:pk>/arquivo/", views.file_download, name="file"),
]
