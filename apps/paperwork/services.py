"""Regras dos documentos da matrícula: quem mantém, o que falta e o aviso às famílias.

- Mantêm (marcam entregue, dispensam, configuram a lista, avisam): secretaria, direção e administração.
- A família vê o que já entregou e o que falta de cada filho (vínculo aprovado). O professor não vê.
"""

from django.urls import reverse
from django.utils import timezone

from apps.core.models import Role
from apps.registry.models import Enrollment, GuardianLink

from .models import RequiredDocument, StudentDocument

MANAGE = (Role.SECRETARIA.value, Role.DIRECAO.value, Role.ADMIN.value)


def can_manage(user):
    return user.is_authenticated and bool(user.school_id) and user.role in MANAGE


def in_use(school):
    """A escola usa o controle quando a secretaria já registrou alguma entrega. Antes disso, nada aparece como
    pendência (a lista inicial existe, mas ninguém deve nada a uma lista que a escola não adotou)."""
    return StudentDocument.objects.filter(document__school=school).exists()


def documents(school):
    """A lista em uso. Na primeira vez, cria a lista inicial (que a escola pode mudar)."""
    if not RequiredDocument.objects.filter(school=school).exists():
        RequiredDocument.objects.bulk_create([
            RequiredDocument(school=school, name=n, mandatory=m, hint=h, position=i)
            for i, (n, m, h) in enumerate(RequiredDocument.DEFAULTS)])
    return list(RequiredDocument.objects.filter(school=school, active=True))


def records(student_ids):
    """{(student_id, document_id): StudentDocument}."""
    return {(r.student_id, r.document_id): r for r in
            StudentDocument.objects.filter(student_id__in=list(student_ids)).select_related("registered_by")}


def missing(student_ids, docs, recs=None):
    """{student_id: [documentos obrigatórios sem registro]} (só quem tem alguma falta)."""
    recs = records(student_ids) if recs is None else recs
    out = {}
    for sid in student_ids:
        lack = [d for d in docs if d.mandatory and (sid, d.pk) not in recs]
        if lack:
            out[sid] = lack
    return out


def current_enrollments(school, class_group=None):
    qs = Enrollment.objects.filter(school=school, status="ativo", student__status="ativo",
                                   class_group__school_year__is_current=True)
    if class_group is not None:
        qs = qs.filter(class_group=class_group)
    return qs.select_related("student", "class_group").order_by("student__first_name", "student__last_name")


def children(user):
    return [ln.student for ln in GuardianLink.objects.filter(guardian=user, status="aprovado", student__status="ativo")
            .select_related("student").order_by("student__first_name")]


def pending_for_family(user):
    kids = children(user)
    if not kids or not in_use(user.school):
        return 0
    lack = missing([s.pk for s in kids], documents(user.school))
    return sum(len(v) for v in lack.values())


def pending_students(school):
    """Quantos estudantes matriculados no ano atual ainda devem algum documento obrigatório."""
    docs = [d for d in RequiredDocument.objects.filter(school=school, active=True, mandatory=True)]
    if not docs or not in_use(school):
        return 0
    ids = list(current_enrollments(school).values_list("student_id", flat=True).distinct())
    return len(missing(ids, docs))


def remind(school, enrollments):
    """Avisa as famílias de quem deve documento, com a lista do que falta. Uma vez por dia por estudante."""
    from apps.communication.family_events import notify_family

    docs = documents(school)
    students = {e.student_id: e.student for e in enrollments}
    lack = missing(list(students), docs)
    today = timezone.localdate()
    total = 0
    for sid, items in lack.items():
        s = students[sid]
        names = "; ".join(d.name for d in items)
        total += notify_family(
            s, "documentos_matricula", f"Documentos da matrícula de {s.first_name} a entregar",
            body=f"Falta entregar na secretaria: {names}.", url=reverse("paperwork:index"), include_student=False,
            dedupe_key=f"documentos:{sid}:{today:%Y%m%d}")
    return total
