from django.urls import path

from . import views

app_name = "coordination"

urlpatterns = [
    path("coordenacao/", views.panel, name="panel"),
    path("coordenacao/registros/", views.record_list, name="records"),
    path("coordenacao/designacoes/", views.designation_list, name="designations"),
    path("coordenacao/designacoes/<int:pk>/encerrar/", views.designation_end, name="designation_end"),
]
