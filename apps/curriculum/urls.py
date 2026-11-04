from django.urls import path

from . import views, views_ontology

app_name = "curriculum"

urlpatterns = [
    path("curriculo/", views.catalog, name="catalog"),
    path("curriculo/seletor/", views.picker_group, name="picker_group"),
    path("curriculo/<int:pk>/", views.item_detail, name="item_detail"),
    path("curriculo/<int:pk>/curadoria/", views_ontology.item_curate, name="item_curate"),
    path("curriculo/mapa/", views_ontology.ontology_map, name="ontology_map"),
    path("curriculo/novo/", views.item_create, name="item_create"),
    path("curriculo/importar/", views.item_import, name="item_import"),
    path("curriculo/curadoria/", views_ontology.curation_queue, name="curation"),
    path("curriculo/acompanhamento/", views.coverage, name="coverage"),
    path("curriculo/evidencias/", views.evidence_list, name="evidence_list"),
    path("curriculo/evidencias/nova/", views.evidence_create, name="evidence_create"),
    path("referencias-normativas/", views.references, name="references"),
]
