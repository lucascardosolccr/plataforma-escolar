from django.urls import path

from . import views, views_official

app_name = "school_calendar"

urlpatterns = [
    path("", views.calendar_index, name="calendar_index"),
    path("oficial/", views_official.official_manage, name="official"),
    path("oficial/<str:kind>/<int:pk>/retirar/", views_official.official_delete, name="official_delete"),
    path("oficial/ano/<int:year_id>/publicar/", views_official.official_publish, name="official_publish"),
]
