"""Currículo (BNCC, Currículo em Movimento do DF) e referências normativas."""

from django.apps import AppConfig


class CurriculumConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.curriculum"
    verbose_name = "Currículo e normas"
