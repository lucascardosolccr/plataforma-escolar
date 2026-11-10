"""Oficinas e atividades com inscrição: vagas, lista de espera e chamada automática de quem espera."""

from django.apps import AppConfig


class WorkshopsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.workshops"
    label = "workshops"
    verbose_name = "Oficinas e inscrições"
