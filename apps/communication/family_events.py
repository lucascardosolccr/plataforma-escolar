"""Avisos automáticos à família sobre o que acontece com o estudante.

Cada evento tem uma chave, um rótulo para a tela de configuração, o tipo de
notificação e se vem ligado por padrão. A direção liga/desliga por escola
(``NotificationRule``); cada pessoa pode silenciar tipos (``NotificationMute``),
menos os que a escola considera essenciais.

Separação pedida pelo Prompt 14:
- registro interno da equipe (observação não compartilhada, registros da
  coordenação, observações internas da atividade) nunca gera aviso à família;
- informação compartilhável (nota, entrega, falta, observação marcada como
  compartilhada) gera aviso, se a regra estiver ligada;
- comunicação institucional (comunicados, cardápio, calendário) e individual
  (mensagens) seguem seus próprios módulos.

Os textos dizem o que aconteceu e onde ver, sem repetir dado sensível.
"""

import datetime

from django.urls import reverse
from django.utils import timezone

from .models import Notification, NotificationMute, NotificationRule

K = Notification.Kind

# chave: (rótulo, tipo de notificação, ligado por padrão)
EVENTS = {
    "nota_publicada": ("Notas de avaliação publicadas", K.EVALUATION, True),
    "nota_alterada": ("Nota alterada depois de publicada", K.GRADE, True),
    "atividade_atribuida": ("Nova atividade de casa", K.ACTIVITY, True),
    "atividade_corrigida": ("Atividade corrigida (nota ou comentário)", K.ACTIVITY, True),
    "entrega_registrada": ("Entrega registrada ou marcada como não entregue", K.ACTIVITY, True),
    "prazo_proximo": ("Lembrete de prazo: atividade não entregue vencendo hoje ou amanhã", K.ACTIVITY, True),
    "falta_registrada": ("Falta registrada", K.ATTENDANCE, True),
    "falta_corrigida": ("Falta corrigida para presença", K.ATTENDANCE, True),
    "limite_faltas": ("Faltas perto do limite", K.ATTENDANCE, True),
    "ocorrencia": ("Ocorrência registrada", K.OCCURRENCE, True),
    "observacao": ("Observação pedagógica compartilhada", K.OBSERVATION, True),
}
#: Tipos que a família não pode silenciar (segurança e vínculo).
ESSENTIAL_KINDS = {K.OCCURRENCE, K.LINK, K.REGISTRATION}
#: Tipos que aparecem nas preferências pessoais.
MUTABLE_KINDS = [K.EVALUATION, K.GRADE, K.ACTIVITY, K.ATTENDANCE, K.OBSERVATION, K.ANNOUNCEMENT, K.MENU,
                 K.CALENDAR, K.MESSAGE]


def event_enabled(school, key):
    rule = NotificationRule.objects.filter(school=school, event=key).first()
    return rule.enabled if rule else EVENTS[key][2]


def family_of(student, include_student=True):
    """Responsáveis com vínculo aprovado (e a conta do próprio estudante)."""
    from apps.registry.models import GuardianLink

    users = [link.guardian for link in GuardianLink.objects.filter(
        student=student, status="aprovado", guardian__is_active=True).select_related("guardian")]
    if include_student and student.user_id and student.user.is_active:
        users.append(student.user)
    return users


def notify_family(student, key, title, body="", url="", dedupe_key="", include_student=True):
    """Avisa a família do estudante sobre o evento ``key``, se a escola deixa
    e a pessoa não silenciou o tipo. Devolve quantos foram avisados."""
    from .services import notify_many

    label, kind, _default = EVENTS[key]
    if not event_enabled(student.school, key):
        return 0
    users = family_of(student, include_student)
    if kind not in ESSENTIAL_KINDS:
        muted = set(NotificationMute.objects.filter(user__in=users, kind=kind).values_list("user_id", flat=True))
        users = [u for u in users if u.pk not in muted]
    notify_many(student.school, users, kind, title, body=body, url=url, student=student, dedupe_key=dedupe_key)
    return len(users)


def student_url(name, student, **extra):
    url = reverse(name)
    return f"{url}?estudante={student.pk}"


def send_deadline_reminders(today=None):
    """Lembra a família da atividade ainda não entregue que vence hoje ou amanhã.

    Um lembrete por estudante e atividade (``dedupe_key``): quem foi lembrado
    na véspera não recebe outro no dia. Não há agendador: o
    ``ScheduledPublicationMiddleware`` chama esta função na primeira
    requisição de cada dia. Só entra quem a atividade alcança (matrícula
    ativa e ``covers``) e ainda não tem entrega registrada. Devolve quantos
    avisos foram tentados.
    """
    from apps.pedagogy.models import Activity, Submission
    from apps.registry.models import Enrollment

    today = today or timezone.localdate()
    tomorrow = today + datetime.timedelta(days=1)
    acts = (Activity.objects.filter(Activity.family_visible_q(today=today), status=Activity.Status.PUBLISHED,
                                    deadline__in=[today, tomorrow])
            .select_related("school", "subject", "class_group"))
    enabled, total = {}, 0
    for act in acts:
        if act.school_id not in enabled:
            enabled[act.school_id] = event_enabled(act.school, "prazo_proximo")
        if not enabled[act.school_id]:
            continue
        delivered = set(Submission.objects.filter(activity=act, status__in=Submission.DELIVERED_STATUSES)
                        .values_list("student_id", flat=True))
        when = "hoje" if act.deadline == today else "amanhã"
        url = reverse("pedagogy:activity_detail", args=[act.pk])
        for enr in (Enrollment.objects.filter(class_group=act.class_group, status="ativo")
                    .select_related("student__school", "student__user")):
            if enr.student_id in delivered or not enr.covers(act.published_date, act.deadline):
                continue
            total += notify_family(
                enr.student, "prazo_proximo", f"Prazo {when}: {act.title}",
                body=f"{enr.student} — {act.subject}, entrega até {act.deadline:%d/%m/%Y}. "
                     "Se já entregou, desconsidere: o professor ainda vai registrar.",
                url=url, dedupe_key=f"prazo:{act.pk}:{enr.student_id}",
            )
    return total
