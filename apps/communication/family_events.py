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

from django.urls import reverse

from .models import Notification, NotificationMute, NotificationRule

K = Notification.Kind

# chave: (rótulo, tipo de notificação, ligado por padrão)
EVENTS = {
    "nota_publicada": ("Notas de avaliação publicadas", K.EVALUATION, True),
    "nota_alterada": ("Nota alterada depois de publicada", K.GRADE, True),
    "atividade_atribuida": ("Nova atividade de casa", K.ACTIVITY, True),
    "atividade_corrigida": ("Atividade corrigida (nota ou comentário)", K.ACTIVITY, True),
    "entrega_registrada": ("Entrega registrada ou marcada como não entregue", K.ACTIVITY, True),
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
