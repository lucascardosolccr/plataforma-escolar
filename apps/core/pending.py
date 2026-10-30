"""Central de pendências: o que cada pessoa precisa resolver, num lugar só.

Cada item diz o que é, quantos são e leva à tela onde se resolve. As
contagens usam as mesmas regras de acesso das telas de destino: ninguém vê
pendência de turma, estudante ou família fora do próprio alcance.
"""

from datetime import timedelta

from django.db.models import Exists, OuterRef, Q
from django.urls import reverse
from django.utils import timezone

from .models import Role


def _item(label, count, url, hint="", tone="attention"):
    return {"label": label, "count": count, "url": url, "hint": hint, "tone": tone}


def for_user(user):
    role = user.role
    items = []
    if role == Role.PROFESSOR.value:
        items += _teacher(user)
    if role in (Role.SECRETARIA.value, Role.ADMIN.value):
        items += _secretaria(user)
    if role in (Role.COORDENACAO.value, Role.DIRECAO.value):
        items += _coordination(user)
    if role == Role.RESPONSAVEL.value:
        items += _family(user)
    if role != Role.ESTUDANTE.value:
        from .views_photo import has_photo, photo_exempt

        if not has_photo(user) and not photo_exempt(user):
            items.append(_item("Sua foto de identificação", 1, reverse("my_photo"), "Leva um minuto.", "info"))
    return [i for i in items if i["count"]]


def _school_days_back(school, n=5):
    """Últimos n dias letivos até ontem (pelo calendário, se publicado; senão dias úteis)."""
    from apps.school_calendar.services import current_year, is_published, school_days

    today = timezone.localdate()
    year = current_year(school)
    if is_published(year):
        days = school_days(year, today - timedelta(days=30), today - timedelta(days=1)) or []
        return days[-n:]
    days, d = [], today - timedelta(days=1)
    while len(days) < n and (today - d).days < 15:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return sorted(days)


def _teacher(user):
    from apps.academics.permissions import pairs_q, teacher_class_ids
    from apps.pedagogy.models import Activity, AttendanceRecord, Evaluation, Grade, Submission
    from apps.printing.models import PrintRequest
    from apps.registry.models import Enrollment

    out = []
    class_ids = teacher_class_ids(user, edit=True)
    days = _school_days_back(user.school)
    done = set(AttendanceRecord.objects.filter(class_group_id__in=class_ids, date__in=days)
               .values_list("class_group_id", "date").distinct())
    missing = sum(1 for c in class_ids for d in days if (c, d) not in done)
    out.append(_item("Chamadas sem registro nos últimos dias letivos", missing,
                     reverse("pedagogy:attendance_list"), f"Considera {len(days)} dia(s) letivo(s) até ontem."))
    evs = Evaluation.objects.filter(school=user.school, date__lt=timezone.localdate()).filter(pairs_q(user, edit=True))
    active = Enrollment.objects.filter(class_group=OuterRef("class_group"), status="ativo")
    no_grades = evs.annotate(has=Exists(Grade.objects.filter(evaluation=OuterRef("pk"), value__isnull=False))) \
        .filter(has=False).filter(Exists(active)).count()
    out.append(_item("Avaliações já aplicadas sem nenhuma nota lançada", no_grades,
                     reverse("pedagogy:evaluation_list") + "?escopo=minhas"))
    acts = Activity.objects.filter(school=user.school, status=Activity.Status.PUBLISHED,
                                   deadline__lt=timezone.localdate()).filter(pairs_q(user, edit=True))
    to_grade = Submission.objects.filter(activity__in=acts, status__in=["entregue", "atrasado"], grade__isnull=True,
                                         comment="").count()
    out.append(_item("Entregas recebidas aguardando correção", to_grade, reverse("pedagogy:activity_list")))
    corr = PrintRequest.objects.filter(requested_by=user, status=PrintRequest.Status.CORRECTION).count()
    out.append(_item("Pedidos de impressão com correção solicitada", corr, reverse("printing:mine")))
    no_date = Activity.objects.filter(school=user.school, class_date__isnull=True,
                                      status=Activity.Status.DRAFT).filter(pairs_q(user, edit=True)).count()
    out.append(_item("Rascunhos de atividade sem data de aplicação", no_date, reverse("pedagogy:activity_list"),
                     tone="info"))
    return out


def _secretaria(user):
    from apps.communication.models import ServiceRequest
    from apps.pedagogy.models import AbsenceJustification
    from apps.printing.models import PrintRequest
    from apps.registry.models import GuardianLink, PhotoException, Student, StudentApplication

    s = user.school
    no_photo = Student.objects.filter(school=s, status="ativo").filter(Q(photo="") | Q(photo__isnull=True)) \
        .exclude(Exists(PhotoException.objects.filter(student=OuterRef("pk")))).count()
    return [
        _item("Pré-cadastros enviados pelas famílias", StudentApplication.objects.filter(
            school=s, status=StudentApplication.Status.SUBMITTED).count(), reverse("application_review_list")),
        _item("Pedidos de vínculo pendentes", GuardianLink.objects.filter(school=s, status="pendente").count(),
              reverse("link_list") + "?status=pendente"),
        _item("Justificativas de falta a analisar", AbsenceJustification.objects.filter(
            school=s, status__in=["recebida", "em_analise"]).count(), reverse("pedagogy:justification_list")),
        _item("Solicitações das famílias em aberto", ServiceRequest.objects.filter(
            school=s, status__in=["recebida", "em_analise"]).count(), reverse("communication:request_list")),
        _item("Impressões aprovadas para imprimir ou entregar", PrintRequest.objects.filter(
            school=s, status__in=["aguardando", "imprimindo", "impressa", "retirada"]).count(),
            reverse("printing:queue") + "?ver=impressao"),
        _item("Estudantes ativos sem foto", no_photo, reverse("photo_pending"), "Não bloqueia nada.", "info"),
    ]


def _coordination(user):
    from apps.coordination.models import CoordinationRecord
    from apps.coordination.print_hooks import pending_print_requests

    today = timezone.localdate()
    return [
        _item("Impressões aguardando sua análise", len(pending_print_requests(user)), reverse("printing:queue")),
        _item("Registros da coordenação com retorno vencido", CoordinationRecord.objects.filter(
            school=user.school, created_by=user, follow_up_on__lt=today).count(), reverse("coordination:records"),
            tone="info"),
    ]


def _family(user):
    from apps.pedagogy.models import AbsenceJustification, AttendanceRecord
    from apps.registry.models import GuardianLink, RegistrationSettings, StudentApplication

    links = GuardianLink.objects.filter(guardian=user, status="aprovado").select_related("student")
    child_ids = [l.student_id for l in links]
    since = timezone.localdate() - timedelta(days=30)
    absences = AttendanceRecord.objects.filter(student_id__in=child_ids, status="falta", date__gte=since)
    covered = 0
    justs = list(AbsenceJustification.objects.filter(student_id__in=child_ids, end_date__gte=since)
                 .values_list("student_id", "start_date", "end_date"))
    for a in absences:
        if any(s == a.student_id and st <= a.date <= en for s, st, en in justs):
            covered += 1
    cfg = RegistrationSettings.for_school(user.school)
    no_photo = sum(1 for l in links if not l.student.photo) if cfg.family_can_send_photo else 0
    return [
        _item("Faltas dos últimos 30 dias sem justificativa enviada", absences.count() - covered,
              reverse("pedagogy:justification_create"), "Só se houver motivo: justificar é opcional.", "info"),
        _item("Fotos de filhos a enviar", no_photo, reverse("my_children")),
        _item("Pré-cadastros com correção pedida pela secretaria", StudentApplication.objects.filter(
            guardian=user, status=StudentApplication.Status.CORRECTION).count(), reverse("family_applications")),
    ]
