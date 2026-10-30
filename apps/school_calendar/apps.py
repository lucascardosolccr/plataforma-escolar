"""Calendário escolar: datas dos módulos e calendário oficial da escola."""

from django.apps import AppConfig


class SchoolCalendarConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.school_calendar"
    verbose_name = "Calendário escolar"
