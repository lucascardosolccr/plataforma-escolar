"""Apoio à inclusão: necessidades específicas, documentos (laudos) e plano individualizado."""

from django.apps import AppConfig


class InclusionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inclusion"
    verbose_name = "Apoio à inclusão"
