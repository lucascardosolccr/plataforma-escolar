"""Conteúdos da prova: preparação para avaliações (Prompt 18 §10)."""

from django.apps import AppConfig


class StudyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.study"
    verbose_name = "Conteúdos da prova"
