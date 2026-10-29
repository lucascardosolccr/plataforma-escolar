from django.urls import path

from . import views

app_name = "school_calendar"

urlpatterns = [
    path("", views.calendar_index, name="calendar_index"),
]
