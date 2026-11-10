from django.urls import path

from . import views

app_name = "supplies"

urlpatterns = [
    path("lista-de-materiais/", views.index, name="index"),
    path("lista-de-materiais/nova/", views.list_form, name="create"),
    path("lista-de-materiais/<int:pk>/", views.detail, name="detail"),
    path("lista-de-materiais/<int:pk>/editar/", views.list_form, name="edit"),
    path("lista-de-materiais/<int:pk>/texto/", views.list_text, name="text"),
    path("lista-de-materiais/<int:pk>/ja-tenho/", views.checks_save, name="checks"),
    path("lista-de-materiais/<int:pk>/incluir/", views.item_add, name="item_add"),
    path("lista-de-materiais/<int:pk>/colar/", views.items_paste, name="paste"),
    path("lista-de-materiais/<int:pk>/enviar/", views.list_submit, name="submit"),
    path("lista-de-materiais/<int:pk>/publicar/", views.list_publish, name="publish"),
    path("lista-de-materiais/<int:pk>/devolver/", views.list_return, name="return"),
    path("lista-de-materiais/<int:pk>/recolher/", views.list_unpublish, name="unpublish"),
    path("lista-de-materiais/<int:pk>/avisar/", views.list_notify, name="notify"),
    path("lista-de-materiais/<int:pk>/copiar/", views.list_duplicate, name="duplicate"),
    path("lista-de-materiais/<int:pk>/apagar/", views.list_delete, name="delete"),
    path("lista-de-materiais/material/<int:pk>/", views.item_edit, name="item_edit"),
    path("lista-de-materiais/material/<int:pk>/retirar/", views.item_delete, name="item_delete"),
    path("lista-de-materiais/material/<int:pk>/mover/", views.item_move, name="item_move"),
]
