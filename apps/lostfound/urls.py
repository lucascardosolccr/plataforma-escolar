from django.urls import path

from . import views

app_name = "lostfound"

urlpatterns = [
    path("achados-e-perdidos/", views.item_list, name="list"),
    path("achados-e-perdidos/novo/", views.item_create, name="create"),
    path("achados-e-perdidos/doar-antigos/", views.donate_old, name="donate_old"),
    path("achados-e-perdidos/<int:pk>/", views.item_detail, name="item"),
    path("achados-e-perdidos/<int:pk>/foto/", views.item_photo, name="photo"),
    path("achados-e-perdidos/<int:pk>/e-meu/", views.item_claim, name="claim"),
    path("achados-e-perdidos/<int:pk>/dono/", views.item_owner, name="owner"),
    path("achados-e-perdidos/<int:pk>/entregar/", views.item_return, name="return"),
    path("achados-e-perdidos/pedido/<int:pk>/recusar/", views.claim_reject, name="claim_reject"),
]
