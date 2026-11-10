"""Regras das oficinas: quem cria e mantém, quem pode se inscrever, vagas e lista de espera.

- Criam: secretaria, direção, administração, coordenação e professor (turmas só do alcance de cada um).
- Mantêm (editar, publicar, encerrar, ver os nomes, tirar inscrição): quem é o responsável pela oficina e a
  secretaria, a direção e a administração. A família nunca vê quem mais se inscreveu.
- Inscrevem: responsáveis com vínculo aprovado de um estudante com matrícula ativa numa turma permitida, até a data
  limite. Vaga cheia = lista de espera; quando alguém confirmado desiste, o primeiro da espera é chamado e a família
  dele recebe um aviso.
"""

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup
from apps.core.models import Role
from apps.registry.models import Enrollment, GuardianLink

from .models import Signup, Workshop

MANAGE_ALL = (Role.SECRETARIA.value, Role.DIRECAO.value, Role.ADMIN.value)
CREATORS = MANAGE_ALL + (Role.COORDENACAO.value, Role.PROFESSOR.value)


def can_create(user):
    return user.is_authenticated and bool(user.school_id) and user.role in CREATORS


def can_manage(user, workshop):
    return can_create(user) and workshop.school_id == user.school_id and (
        user.role in MANAGE_ALL or workshop.organizer_id == user.pk)


def reachable_classes(user):
    from apps.meetings.views_office import reachable_classes as reach

    return reach(user)


def eligible_classes(workshop):
    chosen = workshop.class_groups.all()
    if chosen.exists():
        return chosen
    return ClassGroup.objects.filter(school=workshop.school, school_year__is_current=True)


def children(user):
    return [ln.student for ln in GuardianLink.objects.filter(guardian=user, status="aprovado", student__status="ativo")
            .select_related("student").order_by("student__first_name")]


def eligible_children(user, workshop):
    kids = children(user)
    ids = set(Enrollment.objects.filter(student__in=kids, status="ativo", class_group__in=eligible_classes(workshop))
              .values_list("student_id", flat=True))
    return [s for s in kids if s.pk in ids]


def family_workshops(user, today):
    out = []
    for w in Workshop.objects.filter(school=user.school, published_at__isnull=False, ends_on__gte=today):
        kids = eligible_children(user, w)
        if kids:
            out.append((w, kids))
    return out


def counts(workshop):
    c = {s: 0 for s in Signup.Status.values}
    for status in workshop.signups.values_list("status", flat=True):
        c[status] += 1
    return c


def _tell(signup, title, body, key):
    from apps.communication.family_events import notify_family

    return notify_family(signup.student, "oficinas", title, body=body, url=signup.workshop.get_absolute_url(),
                         include_student=False, dedupe_key=f"oficina:{signup.workshop_id}:{signup.student_id}:{key}")


def sign_up(workshop, student, user):
    """Inscreve (ou põe na espera). Se já estava inscrito ou esperando, não muda nada."""
    with transaction.atomic():
        current = Signup.objects.filter(workshop=workshop, student=student).first()
        if current and current.status != Signup.Status.CANCELED:
            return current
        confirmed = workshop.signups.filter(status=Signup.Status.CONFIRMED).count()
        status = Signup.Status.CONFIRMED if confirmed < workshop.capacity else Signup.Status.WAITING
        signup, _ = Signup.objects.update_or_create(workshop=workshop, student=student, defaults={
            "status": status, "queued_at": timezone.now(), "signed_by": user, "canceled_at": None,
            "canceled_by": None, "cancel_note": ""})
    return signup


def waiting_position(signup):
    if signup.status != Signup.Status.WAITING:
        return None
    return signup.workshop.signups.filter(status=Signup.Status.WAITING, queued_at__lt=signup.queued_at).count() + 1


def cancel(signup, user, note=""):
    """Cancela e, se liberou vaga, chama quem espera. Devolve as inscrições chamadas."""
    with transaction.atomic():
        was_confirmed = signup.status == Signup.Status.CONFIRMED
        signup.status, signup.canceled_at, signup.canceled_by = Signup.Status.CANCELED, timezone.now(), user
        signup.cancel_note = note[:200]
        signup.save(update_fields=["status", "canceled_at", "canceled_by", "cancel_note"])
        return promote(signup.workshop) if was_confirmed else []


def promote(workshop):
    """Enche as vagas livres com a lista de espera, na ordem de inscrição, avisando cada família."""
    called = []
    free = workshop.capacity - workshop.signups.filter(status=Signup.Status.CONFIRMED).count()
    if free <= 0:
        return called
    for s in list(workshop.signups.filter(status=Signup.Status.WAITING).select_related("student", "student__school")
                  [:free]):
        Signup.objects.filter(pk=s.pk, status=Signup.Status.WAITING).update(status=Signup.Status.CONFIRMED)
        s.status = Signup.Status.CONFIRMED
        _tell(s, f"Vaga confirmada: {s.student.first_name} em {workshop.title}",
              f"Abriu uma vaga e {s.student.first_name} saiu da lista de espera. {workshop.schedule}, a partir de "
              f"{workshop.starts_on:%d/%m}. Se não puder participar, cancele para liberar a vaga.",
              f"vaga:{timezone.now():%Y%m%d%H%M%S}")
        called.append(s)
    return called


def announce(workshop):
    """Avisa as famílias das turmas permitidas (um aviso por responsável)."""
    from apps.communication.family_events import notify_family

    students = {e.student for e in Enrollment.objects.filter(
        class_group__in=eligible_classes(workshop), status="ativo", student__status="ativo").select_related(
        "student", "student__school")}
    total = 0
    for s in students:
        total += notify_family(
            s, "oficinas", f"Inscrições abertas: {workshop.title}",
            body=f"{workshop.schedule}, de {workshop.starts_on:%d/%m} a {workshop.ends_on:%d/%m}. "
                 f"{workshop.capacity} vagas; inscrições até {workshop.signup_until:%d/%m}.",
            url=reverse("workshops:detail", args=[workshop.pk]), include_student=False,
            dedupe_key=f"oficina:{workshop.pk}")
    return total
