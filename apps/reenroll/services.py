"""Regras da confirmação de rematrícula.

Quem faz o quê:

- **abrem, encerram, lembram, registram no balcão e exportam:** secretaria, direção e administração;
- **acompanham:** também a coordenação (só leitura);
- **respondem:** os responsáveis com vínculo aprovado, até o prazo (podem mudar a resposta enquanto ele vale).
  O estudante não responde por si: quem não tem responsável com conta responde na secretaria.
"""

import hashlib
import hmac

from django.conf import settings
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Role, create_audit_log

from .models import Answer, Campaign

MANAGE = (Role.SECRETARIA.value, Role.DIRECAO.value, Role.ADMIN.value)
VIEW = MANAGE + (Role.COORDENACAO.value,)
#: Lembrete automático a tantos dias do prazo, para quem ainda não respondeu.
REMIND_DAYS_BEFORE = 3


def can_manage(user):
    return bool(user.school_id) and user.role in MANAGE


def can_view(user):
    return bool(user.school_id) and user.role in VIEW


# ---------------------------------------------------------------- alcance

def origin_classes(campaign):
    """Turmas da campanha: as escolhidas ou, sem escolha, as do ano letivo atual (fora o ano de destino)."""
    from apps.academics.models import ClassGroup

    chosen = campaign.class_groups.all()
    if chosen.exists():
        return chosen
    return ClassGroup.objects.filter(school=campaign.school, school_year__is_current=True).exclude(
        school_year=campaign.target_year_id)


def scope_enrollments(campaign):
    from apps.registry.models import Enrollment

    return (Enrollment.objects.filter(class_group__in=origin_classes(campaign), status="ativo", student__status="ativo")
            .select_related("student", "class_group").order_by("class_group__name", "student__first_name",
                                                                "student__last_name"))


def in_scope(campaign, student):
    return scope_enrollments(campaign).filter(student=student).exists()


def guardian_children(user):
    from apps.registry.models import GuardianLink

    if user.role != Role.RESPONSAVEL.value:
        return []
    return [ln.student for ln in GuardianLink.objects.filter(guardian=user, status="aprovado",
                                                             student__school=user.school)
            .select_related("student").order_by("student__first_name")]


def open_campaigns(school, today=None):
    today = today or timezone.localdate()
    return Campaign.objects.filter(school=school, closed=False, opens_on__lte=today, deadline__gte=today)


def family_rows(user, today=None):
    """[(campanha, [(estudante, resposta ou None)])] das campanhas abertas que alcançam os filhos."""
    kids = guardian_children(user)
    out = []
    if not kids:
        return out
    for c in open_campaigns(user.school, today):
        ids = set(scope_enrollments(c).filter(student__in=kids).values_list("student_id", flat=True))
        if not ids:
            continue
        answers = {a.student_id: a for a in c.answers.filter(student_id__in=ids)}
        out.append((c, [(s, answers.get(s.pk)) for s in kids if s.pk in ids]))
    return out


def pending_for_family(user, today=None):
    return sum(1 for _c, rows in family_rows(user, today) for _s, a in rows if a is None)


def stats(campaign):
    """Totais e linhas por turma: {total, continua, sai, pendente, turmas: [{turma, total, continua, sai, pendente}]}."""
    enrollments = list(scope_enrollments(campaign))
    answers = {a.student_id: a.decision for a in campaign.answers.all()}
    per = {}
    for e in enrollments:
        row = per.setdefault(e.class_group_id, {"turma": e.class_group, "total": 0, "continua": 0, "sai": 0,
                                                "pendente": 0})
        row["total"] += 1
        row[answers.get(e.student_id, "pendente")] += 1
    rows = list(per.values())
    total = {k: sum(r[k] for r in rows) for k in ("total", "continua", "sai", "pendente")}
    return {**total, "turmas": rows}


# ---------------------------------------------------------------- selo

def _key():
    return hashlib.sha256(f"rematricula:{settings.SECRET_KEY}".encode()).digest()


def _payload(a):
    return "|".join(str(x) for x in (
        a.campaign_id, a.student_id, a.decision, a.reason, a.reason_text, a.data_changes, a.accepted_terms,
        a.answered_by_id or "", a.answered_by_name, a.in_person, a.answered_at.isoformat(), a.ip_address or ""))


def seal_for(answer):
    return hmac.new(_key(), _payload(answer).encode("utf-8"), hashlib.sha256).hexdigest()


def intact(answer):
    return hmac.compare_digest(answer.seal or "", seal_for(answer))


def receipt_code(answer):
    from apps.communication.signatures import code_from

    code = code_from(answer.seal)
    return f"{code[:5]}-{code[5:]}"


def record(request, campaign, student, cleaned, in_person=False):
    """Grava (ou substitui) a resposta, com selo e registro na auditoria."""
    user = request.user
    leave = cleaned["decision"] == Answer.Decision.LEAVE
    answer = Answer.objects.filter(campaign=campaign, student=student).first() or Answer(campaign=campaign,
                                                                                        student=student)
    previous = answer.decision if answer.pk else ""
    answer.decision = cleaned["decision"]
    answer.reason = cleaned.get("reason", "") if leave else ""
    answer.reason_text = (cleaned.get("reason_text") or "").strip()
    answer.data_changes = "" if leave else (cleaned.get("data_changes") or "").strip()
    answer.data_done = False if answer.data_changes else answer.data_done
    answer.accepted_terms = bool(cleaned.get("accept")) and not leave
    answer.answered_by = user
    answer.answered_by_name = (cleaned.get("on_behalf") or "").strip() if in_person else (
        user.get_full_name() or user.username)
    answer.in_person = in_person
    answer.answered_at = timezone.now().replace(microsecond=0)
    answer.ip_address = request.META.get("REMOTE_ADDR") or None
    answer.seal = seal_for(answer)
    answer.save()
    verb = f"mudou de “{dict(Answer.Decision.choices)[previous]}” para" if previous and previous != answer.decision \
        else "respondeu"
    create_audit_log(user=user, action="update" if previous else "create", request=request, target=answer,
                     detail=f"Rematrícula ({campaign}): {verb} “{answer.get_decision_display()}” para {student}"
                            + (" (no balcão)" if in_person else ""))
    return answer


# ---------------------------------------------------------------- avisos

def _notify(campaign, students, key_prefix, title, body):
    from apps.communication.family_events import notify_family
    from apps.communication.models import Notification

    url = reverse("reenroll:index")
    n = 0
    for s in students:
        n += bool(notify_family(s, "rematricula", title, body=body, url=url, include_student=False,
                                dedupe_key=f"{key_prefix}:{s.pk}", priority=Notification.Priority.HIGH))
    return n


def announce(campaign):
    students = [e.student for e in scope_enrollments(campaign)]
    n = _notify(campaign, students, f"rematricula:abre:{campaign.pk}", f"{campaign.title}: confirme até "
                f"{campaign.deadline:%d/%m}", "Diga se o estudante continua na escola no ano que vem e confira os "
                "dados de contato. Leva um minuto.")
    campaign.announced_at = timezone.now()
    campaign.save(update_fields=["announced_at"])
    return n


def remind(campaign, today=None):
    today = today or timezone.localdate()
    answered = set(campaign.answers.values_list("student_id", flat=True))
    students = [e.student for e in scope_enrollments(campaign) if e.student_id not in answered]
    n = _notify(campaign, students, f"rematricula:lembrete:{campaign.pk}:{today:%Y%m%d}",
                f"{campaign.title}: o prazo termina em {campaign.deadline:%d/%m}",
                "Ainda falta a sua resposta. Sem ela, a vaga pode não ser garantida: fale com a secretaria se precisar.")
    campaign.reminded_on = today
    campaign.save(update_fields=["reminded_on"])
    return n


def daily(today=None):
    """Rotina diária: avisa a abertura (uma vez) e lembra quem falta a 3 dias do prazo."""
    today = today or timezone.localdate()
    n = 0
    for c in Campaign.objects.filter(closed=False, opens_on__lte=today, deadline__gte=today).select_related("school"):
        if not c.announced_at:
            n += announce(c)
        elif (c.deadline - today).days == REMIND_DAYS_BEFORE and c.reminded_on != today:
            n += remind(c, today)
    return n


def decisions_for(student_ids, school):
    """{estudante: resposta mais recente}, para a rematrícula em lote."""
    out = {}
    for a in (Answer.objects.filter(student_id__in=student_ids, campaign__school=school)
              .select_related("campaign").order_by("campaign__opens_on", "campaign_id")):
        out[a.student_id] = a
    return out


def pending_data_updates(school):
    return Answer.objects.filter(campaign__school=school, decision=Answer.Decision.STAY, data_done=False).exclude(
        Q(data_changes="")).count()
