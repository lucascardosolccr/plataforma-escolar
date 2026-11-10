"""Lista de materiais: o material escolar de cada turma, montado pelo professor, revisado e publicado."""

from django.apps import AppConfig


class SuppliesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.supplies"
    label = "supplies"
    verbose_name = "Lista de materiais"
