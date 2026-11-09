from django.urls import path

from . import views

app_name = "booking"

urlpatterns = [
    path("reservas/", views.agenda, name="agenda"),
    path("reservas/nova/", views.booking_create, name="create"),
    path("reservas/<int:pk>/cancelar/", views.booking_cancel, name="cancel"),
    path("reservas/espacos/", views.resource_list, name="resources"),
    path("reservas/espacos/<int:pk>/", views.resource_edit, name="resource_edit"),
]
