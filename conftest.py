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
    from apps.core.middleware import ScheduledPublicationMiddleware

    ScheduledPublicationMiddleware._last_run = time.monotonic()
    yield
