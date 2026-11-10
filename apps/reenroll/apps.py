"""Confirmação de rematrícula: a família diz se o estudante continua no ano seguinte."""

from django.apps import AppConfig


class ReenrollConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reenroll"
    label = "reenroll"
    verbose_name = "Confirmação de rematrícula"
