"""Biblioteca escolar: acervo de livros, empréstimos, devoluções, reservas e lembretes."""

from django.apps import AppConfig


class LibraryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.library"
    label = "school_library"
    verbose_name = "Biblioteca escolar"
