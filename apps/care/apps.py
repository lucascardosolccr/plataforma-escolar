"""Saúde e emergência do estudante; pessoas autorizadas a buscar e registro da retirada."""

from django.apps import AppConfig


class CareConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.care"
    verbose_name = "Saúde e retirada"
