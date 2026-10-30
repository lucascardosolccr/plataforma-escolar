import time

import pytest


@pytest.fixture(autouse=True)
def _avisos_agendados_sob_controle():
    """Mantém o middleware de avisos agendados fora dos testes que não o testam.

    Ele roda no máximo a cada poucos minutos por processo; sem isto, rodaria na
    primeira requisição de um teste qualquer — e as contagens de consultas
    passariam a depender da ordem dos testes. Os testes do próprio middleware
    zeram ``_last_run`` explicitamente.
    """
    from django.utils import timezone

    from apps.core.middleware import ScheduledPublicationMiddleware

    ScheduledPublicationMiddleware._last_run = time.monotonic()
    ScheduledPublicationMiddleware._last_day = timezone.localdate()
    yield


@pytest.fixture(autouse=True)
def _coordenacao_escola_toda(request):
    """Coordenador criado num teste recebe designação "escola toda".

    É o mesmo que a migração ``coordination 0002`` faz com os coordenadores
    que já existiam: os testes anteriores à designação (Prompt 14) assumem a
    coordenação vendo a escola inteira. Os testes da designação restrita
    desligam isto com ``@pytest.mark.coordenacao_restrita`` ou pelo atributo
    de classe ``coordenacao_restrita = True``.
    """
    if request.node.get_closest_marker("coordenacao_restrita") or getattr(
        request.cls, "coordenacao_restrita", False
    ):
        yield
        return
    from django.db.models.signals import post_save
    from django.utils import timezone

    from apps.core.models import User

    def designar(sender, instance, created, **kwargs):
        if created and instance.role == "coordenacao" and instance.school_id:
            from apps.coordination.models import CoordinatorAssignment

            CoordinatorAssignment.objects.create(
                school_id=instance.school_id, coordinator=instance, all_school=True,
                starts_on=timezone.localdate() - timezone.timedelta(days=3650),
            )

    post_save.connect(designar, sender=User, dispatch_uid="teste-coord-escola-toda")
    yield
    post_save.disconnect(sender=User, dispatch_uid="teste-coord-escola-toda")
