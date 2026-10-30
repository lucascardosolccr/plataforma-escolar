"""Rotina escolar do dia: cardápio do lanche e quadro de horários."""

from django.apps import AppConfig


class RotinaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.rotina"
    verbose_name = "Rotina escolar"
