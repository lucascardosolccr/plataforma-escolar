"""Documentos da matrícula: o que cada estudante já entregou na secretaria e o que ainda falta."""

from django.apps import AppConfig


class PaperworkConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.paperwork"
    label = "paperwork"
    verbose_name = "Documentos da matrícula"
