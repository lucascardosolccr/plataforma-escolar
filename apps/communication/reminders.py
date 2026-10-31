"""Lembretes acadêmicos automáticos (atividades, trabalhos em grupo e provas).

Como funciona:

- A escola define a antecedência em ``ReminderPolicy`` (ex.: ``7,3,1,0``
  dias antes da entrega, ``1`` dia depois do vencimento, ``7,1,0`` para
  provas). Sem configuração, valem os padrões do modelo.
- Cada antecedência é uma "etapa". O lembrete de uma etapa sai uma única vez
  por estudante, compromisso e data (``dedupe_key``). Se o servidor ficou
  desligado e duas etapas passaram, sai só a etapa atual, nunca uma rajada.
- A data faz parte da chave: quando o professor muda o prazo, as etapas
  recomeçam para a nova data, e os avisos antigos ficam marcados como
  resolvidos ("prazo alterado").
- Só é lembrado quem a atividade alcança (matrícula ativa e ``covers``) e
  ainda não tem entrega registrada. Rascunho, publicação agendada e
  atividade cancelada nunca geram lembrete.
- Prova só gera lembrete com a data divulgada (``Evaluation.announced``).
- Não há agendador: ``run_daily`` é chamado pelo
  ``ScheduledPublicationMiddleware`` na primeira requisição do dia e grava um
  ``ReminderRun``. Uma falha fica registrada e é tentada de novo; como cada
  aviso tem chave, repetir não duplica.
"""

import datetime
import logging
import traceback

from django.urls import reverse
from django.utils import timezone

from .models import Notification, ReminderPolicy, ReminderRun

logger = logging.getLogger(__name__)
HIGH = Notification.Priority.HIGH
NORMAL = Notification.Priority.NORMAL


def stage_before(days_left, offsets):
    """Etapa vigente antes da data: a menor antecedência que já foi alcançada.

    Com ``[7, 3, 1, 0]``: faltando 5 dias, etapa 7; faltando 2, etapa 3;
    faltando 9, nenhuma (``None``).
    """
    if days_left < 0:
        return None
    reached = [o for o in offsets if days_left <= o]
    return min(reached) if reached else None


def stage_after(days_over, offsets):
    """Etapa depois do vencimento: o maior atraso configurado já alcançado."""
    if days_over <= 0:
        return None
    reached = [o for o in offsets if o > 0 and days_over >= o]
    return max(reached) if reached else None


def when_text(days_left):
    if days_left == 0:
        return "hoje"
    if days_left == 1:
        return "amanhã"
    return f"em {days_left} dias"


def resolve(ref, reason, student=None, due_on=None):
    """Marca como resolvidos os avisos de um compromisso (entrega registrada,
    atividade cancelada, data alterada). Devolve quantos mudaram."""
    qs = Notification.objects.filter(ref=ref, resolved_at__isnull=True)
    if student is not None:
        qs = qs.filter(student=student)
    if due_on is not None:
        qs = qs.filter(due_on=due_on)
    return qs.update(resolved_at=timezone.now(), resolution=reason[:80])


def _policies():
    cache = {}

    def get(school):
        if school.pk not in cache:
            p = ReminderPolicy.for_school(school)
            cache[school.pk] = (p, ReminderPolicy.parse(p.activity_days), ReminderPolicy.parse(p.overdue_days),
                                ReminderPolicy.parse(p.exam_days))
        return cache[school.pk]
    return get


def _enabled():
    from .family_events import event_enabled

    cache = {}

    def get(school, key):
        if (school.pk, key) not in cache:
            cache[(school.pk, key)] = event_enabled(school, key)
        return cache[(school.pk, key)]
    return get


def activity_reminders(today=None, policies=None, enabled=None):
    """Atividades de casa publicadas: antes do prazo e, se configurado, depois
    do vencimento enquanto continuar pendente."""
    from apps.pedagogy.models import Activity, Submission
    from apps.registry.models import Enrollment

    from .family_events import notify_family

    today = today or timezone.localdate()
    policies = policies or _policies()
    enabled = enabled or _enabled()
    horizon = 60
    acts = (Activity.objects.filter(Activity.family_visible_q(today=today), status=Activity.Status.PUBLISHED,
                                    deadline__gte=today - datetime.timedelta(days=horizon),
                                    deadline__lte=today + datetime.timedelta(days=horizon))
            .select_related("school", "subject", "class_group"))
    total = 0
    for act in acts:
        policy, before, after, _exam = policies(act.school)
        days_left = (act.deadline - today).days
        if days_left >= 0:
            stage, key = stage_before(days_left, before), "prazo_proximo"
            # No dia em que a família recebeu "nova atividade" (que já traz o
            # prazo), o lembrete antecipado seria repetição.
            if stage is not None and days_left > 1 and act.notified_at and \
                    timezone.localdate(act.notified_at) == today:
                stage = None
        else:
            stage, key = stage_after(-days_left, after), "atividade_pendente"
        if stage is None or not enabled(act.school, key):
            continue
        delivered = set(Submission.objects.filter(activity=act, status__in=Submission.DELIVERED_STATUSES)
                        .values_list("student_id", flat=True))
        url = reverse("pedagogy:activity_detail", args=[act.pk])
        for enr in (Enrollment.objects.filter(class_group=act.class_group, status="ativo")
                    .select_related("student__school", "student__user")):
            st = enr.student
            if st.pk in delivered or not enr.covers(act.published_date, act.deadline):
                continue
            if days_left >= 0:
                title = f"Prazo {when_text(days_left)}: {act.title}"
                body = (f"{st} — {act.subject}, entrega até {act.deadline:%d/%m/%Y}. "
                        "Se já entregou, desconsidere: o professor ainda vai registrar.")
                dedupe = f"prazo:{act.pk}:{st.pk}:{act.deadline:%Y%m%d}:{stage}"
                prio = HIGH if days_left <= 1 else NORMAL
            else:
                title = f"Atividade pendente: {act.title}"
                body = (f"{st} — {act.subject}. O prazo era {act.deadline:%d/%m/%Y} e ainda não há entrega "
                        "registrada. Converse com o professor sobre a entrega.")
                dedupe = f"atraso:{act.pk}:{st.pk}:{act.deadline:%Y%m%d}:{stage}"
                prio = HIGH
            total += notify_family(st, key, title, body=body, url=url, dedupe_key=dedupe,
                                   guardians=policy.include_guardians, priority=prio,
                                   ref=f"atividade:{act.pk}", due_on=act.deadline)
    return total


def group_work_reminders(today=None, policies=None, enabled=None):
    """Trabalhos em grupo: cada integrante atual cujo grupo (ou ele, na
    entrega individual) ainda não tem entrega registrada."""
    from apps.pedagogy.models import GroupWork, GroupWorkDelivery, WorkGroupMember

    from .family_events import notify_family

    today = today or timezone.localdate()
    policies = policies or _policies()
    enabled = enabled or _enabled()
    delivered_states = (GroupWorkDelivery.Status.DELIVERED, GroupWorkDelivery.Status.LATE)
    works = (GroupWork.objects.filter(GroupWork.family_visible_q(today=today), status=GroupWork.Status.PUBLISHED,
                                      deadline__gte=today, deadline__lte=today + datetime.timedelta(days=60))
             .select_related("school", "subject"))
    total = 0
    for work in works:
        policy, before, _after, _exam = policies(work.school)
        days_left = (work.deadline - today).days
        stage = stage_before(days_left, before)
        if stage is not None and days_left > 1 and work.notified_at and \
                timezone.localdate(work.notified_at) == today:
            stage = None
        if stage is None or not enabled(work.school, "prazo_proximo"):
            continue
        done = GroupWorkDelivery.objects.filter(group_work=work, status__in=delivered_states)
        done_groups = set(done.filter(student__isnull=True).values_list("group_id", flat=True))
        done_students = set(done.filter(student__isnull=False).values_list("student_id", flat=True))
        url = reverse("pedagogy:group_work_detail", args=[work.pk])
        for m in (WorkGroupMember.objects.filter(group__group_work=work, removed_at__isnull=True)
                  .select_related("student__school", "student__user")):
            if m.group_id in done_groups or m.student_id in done_students:
                continue
            total += notify_family(
                m.student, "prazo_proximo", f"Prazo {when_text(days_left)}: {work.title} (trabalho em grupo)",
                body=f"{m.student} — {work.subject}, entrega até {work.deadline:%d/%m/%Y}. "
                     "Se o grupo já entregou, desconsidere: o professor ainda vai registrar.",
                url=url, dedupe_key=f"prazo-trabalho:{work.pk}:{m.student_id}:{work.deadline:%Y%m%d}:{stage}",
                guardians=policy.include_guardians, priority=HIGH if days_left <= 1 else NORMAL,
                ref=f"trabalho:{work.pk}", due_on=work.deadline,
            )
    return total


def exam_students(ev):
    """Estudantes da turma com matrícula ativa que alcança a data da prova."""
    from apps.registry.models import Enrollment

    return [e.student for e in Enrollment.objects.filter(class_group=ev.class_group, status="ativo")
            .select_related("student__school", "student__user")
            if e.covers(ev.date)]


def exam_reminders(today=None, policies=None, enabled=None):
    """Provas com data divulgada: lembretes antes da data (padrão 7, 1 e 0)."""
    from apps.pedagogy.models import Evaluation

    from .family_events import notify_family

    today = today or timezone.localdate()
    policies = policies or _policies()
    enabled = enabled or _enabled()
    total = 0
    evs = (Evaluation.objects.filter(announced=True, date__gte=today, date__lte=today + datetime.timedelta(days=60))
           .select_related("school", "subject", "class_group"))
    for ev in evs:
        policy, _b, _a, offsets = policies(ev.school)
        days_left = (ev.date - today).days
        stage = stage_before(days_left, offsets)
        if stage is None or not enabled(ev.school, "prova_lembrete"):
            continue
        for st in exam_students(ev):
            total += notify_family(
                st, "prova_lembrete", f"Prova {when_text(days_left)}: {ev.title}",
                body=f"{st} — {ev.subject}, turma {ev.class_group}, em {ev.date:%d/%m/%Y}.",
                url=agenda_url(), dedupe_key=f"prova:{ev.pk}:{st.pk}:{ev.date:%Y%m%d}:{stage}",
                guardians=policy.include_guardians, priority=HIGH if days_left <= 1 else NORMAL,
                ref=f"avaliacao:{ev.pk}", due_on=ev.date,
            )
    return total


def agenda_url():
    return reverse("school_calendar:calendar_index") + "?type=evaluation"


def run_daily(today=None):
    """Processa todos os lembretes do dia e registra o resultado."""
    today = today or timezone.localdate()
    run = ReminderRun.objects.create(day=today)
    policies, enabled = _policies(), _enabled()
    counts = {}
    try:
        counts["atividades"] = activity_reminders(today, policies, enabled)
        counts["trabalhos"] = group_work_reminders(today, policies, enabled)
        counts["provas"] = exam_reminders(today, policies, enabled)
        counts["alertas_pedagogicos"] = _learning_alerts(today)
    except Exception:
        run.status = ReminderRun.Status.ERROR
        run.detail = traceback.format_exc()[-2000:]
        run.sent = sum(counts.values())
        run.finished_at = timezone.now()
        run.save()
        raise
    run.status = ReminderRun.Status.OK
    run.sent = sum(counts.values())
    run.detail = ", ".join(f"{k}: {v}" for k, v in counts.items())
    run.finished_at = timezone.now()
    run.save()
    return run


def done_today(today=None):
    today = today or timezone.localdate()
    return ReminderRun.objects.filter(day=today, status=ReminderRun.Status.OK).exists()


def resolve_delivered_activity(act):
    """Entrega registrada encerra os lembretes daquele estudante."""
    from apps.pedagogy.models import Submission

    total = 0
    for sub in Submission.objects.filter(activity=act, status__in=Submission.DELIVERED_STATUSES).select_related(
            "student"):
        total += resolve(f"atividade:{act.pk}", "Entrega registrada", student=sub.student)
    return total


def resolve_delivered_group_work(work):
    """Grupo (ou integrante, na entrega individual) com entrega registrada."""
    from apps.pedagogy.models import GroupWorkDelivery, WorkGroupMember

    done = GroupWorkDelivery.objects.filter(
        group_work=work, status__in=(GroupWorkDelivery.Status.DELIVERED, GroupWorkDelivery.Status.LATE))
    done_groups = set(done.filter(student__isnull=True).values_list("group_id", flat=True))
    done_students = set(done.filter(student__isnull=False).values_list("student_id", flat=True))
    total = 0
    for m in WorkGroupMember.objects.filter(group__group_work=work).select_related("student"):
        if m.group_id in done_groups or m.student_id in done_students:
            total += resolve(f"trabalho:{work.pk}", "Entrega registrada", student=m.student)
    return total


def notify_exam_change(ev, old_date=None, was_announced=False, deleted=False):
    """Prova marcada, remarcada ou desmarcada: avisa estudantes e famílias.

    Só fala do que a turma já sabia ou passa a saber: prova nunca divulgada
    não gera aviso de mudança. Datas passadas não geram aviso.
    """
    from .family_events import notify_family

    today = timezone.localdate()
    ref = f"avaliacao:{ev.pk}"
    now_public = ev.announced and not deleted
    if not now_public:
        if was_announced and old_date and old_date >= today:
            resolve(ref, "Prova desmarcada")
            for st in exam_students(ev):
                notify_family(st, "prova_marcada", f"Prova desmarcada: {ev.title}",
                              body=f"{st} — {ev.subject}. A prova prevista para {old_date:%d/%m/%Y} foi desmarcada.",
                              url=agenda_url(), dedupe_key=f"prova-desmarcada:{ev.pk}:{old_date:%Y%m%d}",
                              priority=HIGH, ref=ref, due_on=old_date)
            resolve(ref, "Prova desmarcada")
        return
    if ev.date < today:
        return
    if was_announced and old_date == ev.date:
        return
    if was_announced and old_date:
        resolve(ref, f"Data alterada para {ev.date:%d/%m/%Y}")
        title = f"Data da prova alterada: {ev.title}"
        body_tail = f"passou de {old_date:%d/%m/%Y} para {ev.date:%d/%m/%Y}."
        key = f"prova-alterada:{ev.pk}:{ev.date:%Y%m%d}"
    else:
        title = f"Prova marcada: {ev.title}"
        body_tail = f"marcada para {ev.date:%d/%m/%Y}."
        key = f"prova-marcada:{ev.pk}:{ev.date:%Y%m%d}"
    for st in exam_students(ev):
        notify_family(st, "prova_marcada", title, body=f"{st} — {ev.subject}, turma {ev.class_group}: {body_tail}",
                      url=agenda_url(), dedupe_key=key, priority=HIGH if was_announced else NORMAL,
                      ref=ref, due_on=ev.date)



def _learning_alerts(today):
    """Recalcula os alertas do EIA-Cognitio uma vez por dia (regras explícitas)."""
    from apps.cognitio.alerts import generate_for_school
    from apps.core.models import School

    return sum(generate_for_school(s, today) for s in School.objects.all())
