from django.urls import path

from . import views

app_name = "meetings"

urlpatterns = [
    path("reunioes/", views.meeting_list, name="list"),
    path("reunioes/nova/", views.meeting_create, name="create"),
    path("reunioes/<int:pk>/", views.meeting_detail, name="detail"),
    path("reunioes/<int:pk>/editar/", views.meeting_edit, name="edit"),
    path("reunioes/<int:pk>/registro/", views.meeting_record, name="record"),
    path("reunioes/<int:pk>/cancelar/", views.meeting_cancel, name="cancel"),
    path("reunioes/<int:pk>/encaminhamentos/", views.follow_up_add, name="follow_up_add"),
    path("reunioes/<int:pk>/encaminhamentos/<int:follow_up_id>/", views.follow_up_update,
         name="follow_up_update"),
]
