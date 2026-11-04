"""Carteirinha do estudante e portaria (entrada, atraso e saída)."""

from django.apps import AppConfig


class GateConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.gate"
    verbose_name = "Carteirinha e portaria"
