"""Achados e perdidos: objetos encontrados na escola, reconhecidos pela família e entregues com registro."""

from django.apps import AppConfig


class LostFoundConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.lostfound"
    verbose_name = "Achados e perdidos"
