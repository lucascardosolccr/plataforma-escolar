"""Resumo semanal dos sinais novos do EIA-Cognitio para professores e coordenação.

Os alertas são recalculados todo dia (``alerts.generate_for_school``), mas a central de pendências só mostra
os de nível "importante". Sem um aviso, um sinal novo de queda (nível "atenção") esperava alguém abrir a
tela de alertas, o que contraria a ideia de detectar cedo.

Regras: no máximo um aviso por pessoa por semana (chave por semana ISO), só quando há sinal novo desde o
último resumo, só das turmas que a pessoa alcança (a mesma regra da tela de alertas) e só com contagens por
regra: nenhum nome de estudante no texto do aviso. Quem não quiser recebê-lo silencia o tipo nas
preferências de notificação.
"""

import datetime
from collections import Counter

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Role

PREFIX = "eia-semana"
ROLES = (Role.PROFESSOR.value, Role.COORDENACAO.value)


def weekly_digest(today=None):
    from apps.communication.models import Notification, NotificationMute
    from apps.communication.services import notify_many

    from .alerts import RULES
    from .views_intel import _alerts_visible

    today = today or timezone.localdate()
    year, week, _ = today.isocalendar()
    muted = set(NotificationMute.objects.filter(kind=Notification.Kind.EIA).values_list("user_id", flat=True))
    sent = 0
    for user in get_user_model().objects.filter(role__in=ROLES, is_active=True, school__isnull=False) \
            .exclude(pk__in=muted).select_related("school"):
        key = f"{PREFIX}:{user.pk}:{year}-{week:02d}"
        if Notification.objects.filter(user=user, dedupe_key=key).exists():
            continue
        last = (Notification.objects.filter(user=user, dedupe_key__startswith=f"{PREFIX}:{user.pk}:")
                .order_by("-created_at").values_list("created_at", flat=True).first())
        since = last or timezone.now() - datetime.timedelta(days=7)
        new = _alerts_visible(user).filter(active=True, created_at__gt=since) \
            .exclude(status__in=["descartado", "resolvido"])
        counts = Counter(new.values_list("rule", flat=True))
        total = sum(counts.values())
        if not total:
            continue
        body = "; ".join(f"{RULES.get(rule, rule)}: {n}" for rule, n in counts.most_common())
        sent += notify_many(user.school, [user], Notification.Kind.EIA,
                            f"EIA-Cognitio: {total} sinal(is) novo(s) nas suas turmas nesta semana",
                            body=body, url=reverse("cognitio:alerts"), dedupe_key=key)
    return sent
