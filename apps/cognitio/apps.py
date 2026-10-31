"""EIA-Cognitio: inteligência analítica, preditiva e prescritiva da aprendizagem."""

from django.apps import AppConfig


class CognitioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.cognitio"
    verbose_name = "EIA-Cognitio"

    def ready(self):
        from . import signals

        signals.connect()
