from django.urls import path

from . import views

app_name = "curriculum"

urlpatterns = [
    path("curriculo/", views.catalog, name="catalog"),
    path("curriculo/<int:pk>/", views.item_detail, name="item_detail"),
    path("curriculo/novo/", views.item_create, name="item_create"),
    path("curriculo/importar/", views.item_import, name="item_import"),
    path("curriculo/acompanhamento/", views.coverage, name="coverage"),
    path("curriculo/evidencias/", views.evidence_list, name="evidence_list"),
    path("curriculo/evidencias/nova/", views.evidence_create, name="evidence_create"),
    path("referencias-normativas/", views.references, name="references"),
]
