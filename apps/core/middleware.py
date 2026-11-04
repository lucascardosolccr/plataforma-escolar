"""Obriga a troca de senha temporária antes de usar a plataforma.

Sem isto, uma senha gerada pela secretaria e entregue em papel continuaria
valendo indefinidamente — e quem a viu no caminho continuaria com acesso.
"""

import logging
import threading
import time

from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)


class ForcePasswordChangeMiddleware:
    """Redireciona para a troca de senha enquanto a conta estiver marcada.

    As exceções abaixo são obrigatórias: sem elas o usuário não consegue nem
    trocar a senha nem sair, e fica preso num ciclo de redirecionamento.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, "must_change_password", False)
        ):
            permitidas = {
                reverse("password_change"),
                reverse("password_change_done"),
                reverse("logout"),
            }
            if request.path not in permitidas and not request.path.startswith(
                ("/static/", "/admin/")
            ):
                return redirect("password_change")
        return self.get_response(request)


class ScheduledPublicationMiddleware:
    """Entrega os avisos de atividades e trabalhos agendados quando a data chega.

    A plataforma roda sem agendador (sem cron, sem fila, sem serviço externo).
    Em vez disso, a primeira requisição autenticada depois do intervalo confere
    se há publicação agendada vencida e avisa as famílias. O custo é uma
    consulta curta a cada ``INTERVAL`` segundos por processo, não por página —
    e sempre na primeira requisição de um novo dia, para a publicação agendada
    não esperar o intervalo depois da meia-noite.
    Na primeira requisição de cada dia também saem os lembretes de prazo e de
    prova (``communication.reminders.run_daily``), registrados em
    ``ReminderRun``. Se o processamento falhar, ele é tentado de novo na
    próxima rodada do intervalo; o dia só fica dado como feito com uma
    execução concluída.
    Uma falha aqui nunca derruba a página: o aviso fica para a próxima vez.
    """

    INTERVAL = 300
    _last_run = None
    _last_day = None
    _last_reminder_day = None

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        agora = time.monotonic()
        hoje = timezone.localdate()
        ultima = ScheduledPublicationMiddleware._last_run
        if (
            user is not None
            and user.is_authenticated
            and (
                ultima is None
                or agora - ultima >= self.INTERVAL
                or hoje != ScheduledPublicationMiddleware._last_day
            )
        ):
            ScheduledPublicationMiddleware._last_run = agora
            ScheduledPublicationMiddleware._last_day = hoje
            from apps.communication.services import deliver_due_publications

            try:
                deliver_due_publications()
            except Exception:  # o aviso não pode quebrar a navegação
                logger.exception("Falha ao entregar avisos de publicações agendadas")
            self._gate_missing()
            # Lembretes: uma vez por dia (o registro em ReminderRun vale
            # entre processos; o dedupe_key de cada aviso cobre corridas).
            if ScheduledPublicationMiddleware._last_reminder_day != hoje:
                from django.conf import settings

                if getattr(settings, "DAILY_JOBS_IN_BACKGROUND", False):
                    # Em segundo plano: a rotina (lembretes, alertas do EIA, resumo semanal) levava segundos e
                    # a primeira pessoa do dia esperava por ela (4 s na base de escala, 04/11/2026).
                    ScheduledPublicationMiddleware._last_reminder_day = hoje
                    threading.Thread(target=self._daily_in_background, args=(hoje,), daemon=True,
                                     name="rotina-diaria").start()
                else:
                    self._daily(hoje)
        return self.get_response(request)

    _daily_lock = threading.Lock()
    _gate_lock = threading.Lock()

    @classmethod
    def _gate_missing(cls):
        """Aviso de "ainda sem entrada na portaria": uma consulta para saber se alguma escola ligou; o trabalho
        roda em segundo plano (ou síncrono nos testes)."""
        from django.conf import settings

        from apps.gate.models import GateSettings

        try:
            schools = [g.school for g in GateSettings.objects.filter(notify_missing_after__isnull=False)
                       .select_related("school")]
        except Exception:
            logger.exception("Falha ao consultar a configuração da portaria")
            return
        if not schools:
            return
        if getattr(settings, "DAILY_JOBS_IN_BACKGROUND", False):
            threading.Thread(target=cls._gate_missing_run, args=(schools, True), daemon=True,
                             name="portaria-sem-entrada").start()
        else:
            cls._gate_missing_run(schools, False)

    @classmethod
    def _gate_missing_run(cls, schools, background):
        from django.db import connections

        from apps.gate.services import notify_missing

        if not cls._gate_lock.acquire(blocking=False):
            return
        try:
            for school in schools:
                notify_missing(school)
        except Exception:
            logger.exception("Falha ao avisar famílias de estudantes sem entrada na portaria")
        finally:
            cls._gate_lock.release()
            if background:
                connections.close_all()

    @staticmethod
    def _daily(hoje):
        from apps.communication import reminders

        try:
            if not reminders.done_today(hoje):
                reminders.run_daily(hoje)
            ScheduledPublicationMiddleware._last_reminder_day = hoje
            return True
        except Exception:
            ScheduledPublicationMiddleware._last_reminder_day = None  # o dia não fica dado como feito
            logger.exception("Falha ao processar os lembretes; nova tentativa no próximo intervalo")
            return False

    @classmethod
    def _daily_in_background(cls, hoje):
        from django.db import connections

        if not cls._daily_lock.acquire(blocking=False):  # outra thread já está rodando a rotina
            return
        try:
            cls._daily(hoje)
        finally:
            cls._daily_lock.release()
            connections.close_all()  # a thread abriu as próprias conexões


class ContentSecurityPolicyMiddleware:
    """Só o próprio servidor da escola entrega conteúdo às páginas.

    Fontes, ícones ou scripts de CDN entregam o IP e o horário de acesso de
    famílias e estudantes a terceiros, sem base legal (LGPD), e deixam a
    plataforma quebrada numa rede local sem internet. A política bloqueia
    qualquer origem externa: um CDN reintroduzido por engano falha à vista em
    vez de voltar em silêncio.

    Scripts: só arquivos do próprio servidor. Nenhum ``<script>`` embutido nem
    ``onclick``/``onchange`` nos templates (o teste ``test_no_inline_script``
    garante); as interações usam atributos ``data-*`` lidos por ``ds.js``.
    Assim, um texto malicioso que escapasse do escape automático ainda não
    conseguiria executar código. Estilos idem: nenhum ``style=""`` nem
    ``<style>`` (larguras de gráfico vão como atributo de SVG, intensidade do
    mapa de calor como classe). ``data:`` cobre os ícones SVG embutidos no CSS
    do Bootstrap.
    """

    POLICY = "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self'",
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", self.POLICY)
        return response
