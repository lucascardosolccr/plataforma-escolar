"""Histórico de atualizações e avisos dos conteúdos da prova.

Avisos (pela central de notificações da própria plataforma, regra
"conteudo_prova" das preferências da escola):
- publicação: uma vez, quando a data de visibilidade chega (``notified_at``);
- data da prova alterada: aviso "importante", um por nova data;
- material incluído, retirado ou trocado: no máximo um aviso por dia por prova,
  para não encher a caixa da família.
Sem a data de visibilidade, nada é avisado: o link responderia "acesso negado".
"""

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import ExamGuide, GuideUpdate


def _students(guide):
    """Estudantes alcançados pela prova (matrícula cobrindo o período), para avisar."""
    from apps.pedagogy.access import enrollments_by_student, reaches
    from apps.registry.models import Enrollment, Student

    ids = Enrollment.objects.filter(class_group=guide.class_group).values_list("student_id", flat=True)
    by = enrollments_by_student(ids, guide.class_group_id)
    reached = [sid for sid, enrs in by.items() if reaches(enrs, guide)]
    return Student.objects.filter(pk__in=reached, status="ativo").select_related("user", "school")


def _notify(guide, title, body, dedupe, priority="normal"):
    from apps.communication.family_events import notify_family

    if not guide.is_visible_to_family:
        return 0
    url = reverse("study:detail", args=[guide.pk])
    total = 0
    for student in _students(guide):
        total += notify_family(student, "conteudo_prova", title, body=body, url=url,
                               dedupe_key=f"{dedupe}-{student.pk}", priority=priority, due_on=guide.exam_date,
                               ref=f"guia:{guide.pk}")
    return total


def log(guide, kind, text, user=None):
    return GuideUpdate.objects.create(guide=guide, kind=kind, text=text[:300], user=user)


def announce(guide):
    """Avisa a publicação uma única vez, quando ela fica visível."""
    if not guide.is_visible_to_family:
        return False
    with transaction.atomic():
        claimed = ExamGuide.objects.filter(pk=guide.pk, notified_at__isnull=True).update(notified_at=timezone.now())
        if not claimed:
            return False
        guide.notified_at = timezone.now()
        _notify(guide, f"Conteúdos da prova: {guide.title}",
                f"{guide.subject}, turma {guide.class_group}. Prova em {guide.exam_date:%d/%m/%Y}.",
                f"guia-{guide.pk}-publicado")
    return True


def date_changed(guide, old_date, user=None):
    if old_date == guide.exam_date:
        return 0
    log(guide, GuideUpdate.Kind.DATE, f"Data da prova: {old_date:%d/%m/%Y} → {guide.exam_date:%d/%m/%Y}", user)
    if guide.notified_at is None:
        return 0
    return _notify(guide, f"Data da prova alterada: {guide.title}",
                   f"A prova passou de {old_date:%d/%m/%Y} para {guide.exam_date:%d/%m/%Y}.",
                   f"guia-{guide.pk}-data-{guide.exam_date:%Y%m%d}", priority="importante")


def content_changed(guide, kind, text, user=None):
    """Material ou tópico mudou depois de publicado: registra e avisa (1×/dia)."""
    log(guide, kind, text, user)
    if guide.notified_at is None:
        return 0
    return _notify(guide, f"Conteúdos da prova atualizados: {guide.title}", text,
                   f"guia-{guide.pk}-atualizacao-{timezone.localdate():%Y%m%d}")


def sync_evaluation_date(evaluation, old_date, user=None):
    """A avaliação mudou de data: os conteúdos ligados a ela acompanham."""
    if old_date == evaluation.date:
        return 0
    total = 0
    for guide in ExamGuide.objects.filter(evaluation=evaluation).select_related("class_group", "subject", "school"):
        previous = guide.exam_date
        guide.exam_date = evaluation.date
        guide.save(update_fields=["exam_date", "updated_at"])
        total += date_changed(guide, previous, user) or 0
    return total


def deliver_due_guides(school=None):
    """Publicações com data futura: avisa quando a data chega (chamado pelo
    ``ScheduledPublicationMiddleware``, como as atividades agendadas)."""
    due = ExamGuide.objects.filter(status=ExamGuide.Status.PUBLISHED, notified_at__isnull=True,
                                   published_date__lte=timezone.localdate()).select_related(
        "school", "class_group", "subject")
    if school is not None:
        due = due.filter(school=school)
    return sum(1 for g in due if announce(g))
