"""Trajetória escolar: os anos anteriores de cada estudante, o diagnóstico ao longo dos anos e as previsões validadas."""

from django.apps import AppConfig


class LongitudinalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.longitudinal"
    label = "longitudinal"
    verbose_name = "Trajetória escolar"
