"""Regras da biblioteca num lugar só: emprestar, devolver, renovar, reservar e os lembretes do dia.

Cada operação roda numa transação (SQLite em modo IMMEDIATE): dois balcões não emprestam o último exemplar ao
mesmo tempo. Os avisos à família saem depois da transação.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from apps.core.models import create_audit_log

from .access import settings_for
from .models import Book, Loan, Reservation


class LibraryError(Exception):
    """Regra da biblioteca impediu a operação; a mensagem vai para a tela."""


def due_date(school, start, days):
    """Devolução em ``days`` dias; se cair em dia sem aula (fim de semana, feriado, férias), vai para o próximo dia
    letivo do calendário oficial. Sem calendário, só pula o fim de semana."""
    from apps.school_calendar.services import current_year, next_school_day, school_days

    due = start + timedelta(days=days)
    year = current_year(school)
    known = school_days(year, due, due) if year else None
    if known == [] and year.start_date <= due <= year.end_date:
        due = next_school_day(year, due - timedelta(days=1)) or due
    if due.weekday() >= 5:
        due += timedelta(days=7 - due.weekday())
    return due


def class_names(students):
    """{estudante: turma da matrícula ativa}, para diferenciar homônimos nas buscas."""
    from apps.registry.models import Enrollment

    return {e.student_id: e.class_group.name for e in Enrollment.objects.filter(
        student__in=students, status="ativo").select_related("class_group")}


def counts(books):
    """{livro: (emprestados, separados, na fila)} de uma vez, para listas."""
    ids = [b.pk for b in books]
    out = {pk: [0, 0, 0] for pk in ids}
    for row in Loan.objects.filter(book_id__in=ids, returned_at__isnull=True).values("book_id").annotate(n=Count("pk")):
        out[row["book_id"]][0] = row["n"]
    for row in (Reservation.objects.filter(book_id__in=ids, status__in=Reservation.OPEN).values("book_id", "status")
                .annotate(n=Count("pk"))):
        out[row["book_id"]][1 if row["status"] == Reservation.Status.READY else 2] += row["n"]
    return out


def available(book):
    lent, held, _waiting = counts([book])[book.pk]
    return max(0, book.copies - lent - held)


def _notify(student, title, body, dedupe_key, high=False):
    from apps.communication.family_events import notify_family
    from apps.communication.models import Notification

    return notify_family(student, "biblioteca", title, body=body, url=reverse("library:mine"), dedupe_key=dedupe_key,
                         priority=Notification.Priority.HIGH if high else Notification.Priority.NORMAL)


def lend(book, student, user, request=None, today=None):
    today = today or timezone.localdate()
    cfg = settings_for(book.school)
    with transaction.atomic():
        book = Book.objects.get(pk=book.pk)
        if not book.active:
            raise LibraryError("Este livro saiu do acervo.")
        if student.school_id != book.school_id or student.status != "ativo":
            raise LibraryError("Só estudantes com matrícula ativa na escola pegam livros.")
        open_loans = list(Loan.objects.filter(student=student, returned_at__isnull=True).select_related("book"))
        if any(ln.book_id == book.pk for ln in open_loans):
            raise LibraryError(f"{student.first_name} já está com este livro.")
        late = [ln for ln in open_loans if ln.due_on < today]
        if late:
            raise LibraryError(f"{student.first_name} está com “{late[0].book.title}” atrasado desde "
                               f"{late[0].due_on:%d/%m}. Primeiro a devolução, depois um livro novo.")
        if len(open_loans) >= cfg.max_loans:
            raise LibraryError(f"{student.first_name} já está com {len(open_loans)} livro(s), o limite da escola.")
        held = Reservation.objects.filter(book=book, student=student, status=Reservation.Status.READY).first()
        if not held and available(book) <= 0:
            raise LibraryError("Nenhum exemplar livre agora. Coloque o estudante na fila de reserva.")
        loan = Loan.objects.create(school=book.school, book=book, student=student, lent_at=timezone.now(),
                                   due_on=due_date(book.school, today, cfg.loan_days), lent_by=user)
        Reservation.objects.filter(book=book, student=student, status__in=Reservation.OPEN).update(
            status=Reservation.Status.DONE)
        create_audit_log(user=user, action="create", request=request, target=loan,
                         detail=f"Emprestou “{book.title}” a {student} até {loan.due_on:%d/%m/%Y}")
    _notify(student, f"Livro emprestado: {book.title}",
            f"{student.first_name} pegou o livro na biblioteca. Devolver até {loan.due_on:%d/%m/%Y}.",
            f"biblioteca:emprestimo:{loan.pk}")
    return loan


def give_back(loan, user, note="", request=None, today=None):
    with transaction.atomic():
        loan = Loan.objects.select_related("book", "student").get(pk=loan.pk)
        if loan.returned_at:
            raise LibraryError("Esta devolução já foi registrada.")
        late = loan.days_late(today)
        loan.returned_at, loan.returned_by, loan.condition_note = timezone.now(), user, note[:200]
        loan.save(update_fields=["returned_at", "returned_by", "condition_note"])
        create_audit_log(user=user, action="update", request=request, target=loan,
                         detail=f"Registrou a devolução de “{loan.book.title}” por {loan.student}"
                                + (f", {late} dia(s) de atraso" if late else "") + (f" ({note})" if note else ""))
    promote(loan.book, today)
    return loan


def promote(book, today=None):
    """Exemplar livre e gente na fila: separa para o primeiro e avisa. Devolve quantos foram separados."""
    today = today or timezone.localdate()
    cfg = settings_for(book.school)
    done = []
    with transaction.atomic():
        while available(book) > 0:
            nxt = Reservation.objects.filter(book=book, status=Reservation.Status.WAITING).select_related(
                "student").first()
            if nxt is None:
                break
            nxt.status, nxt.ready_on = Reservation.Status.READY, today
            nxt.expires_on = due_date(book.school, today, cfg.hold_days)
            nxt.save(update_fields=["status", "ready_on", "expires_on"])
            done.append(nxt)
    for r in done:
        _notify(r.student, f"Livro reservado separado: {book.title}",
                f"Chegou a vez de {r.student.first_name}. Retire na biblioteca até {r.expires_on:%d/%m/%Y}; depois "
                f"disso, o livro passa para o próximo da fila.", f"biblioteca:separado:{r.pk}", high=True)
    return len(done)


def renew(loan, user, request=None, today=None):
    today = today or timezone.localdate()
    cfg = settings_for(loan.school)
    with transaction.atomic():
        loan = Loan.objects.select_related("book", "student").get(pk=loan.pk)
        if loan.returned_at:
            raise LibraryError("Este livro já foi devolvido.")
        if loan.due_on < today:
            raise LibraryError("Livro atrasado não renova: devolva na biblioteca.")
        if loan.renewals >= cfg.max_renewals:
            raise LibraryError("Já usou as renovações permitidas pela escola.")
        if Reservation.objects.filter(book=loan.book, status=Reservation.Status.WAITING).exists():
            raise LibraryError("Tem gente na fila por este livro: não dá para renovar.")
        loan.due_on, loan.renewals = due_date(loan.school, today, cfg.loan_days), loan.renewals + 1
        loan.save(update_fields=["due_on", "renewals"])
        create_audit_log(user=user, action="update", request=request, target=loan,
                         detail=f"Renovou “{loan.book.title}” de {loan.student} até {loan.due_on:%d/%m/%Y}")
    return loan


def reserve(book, student, user, request=None):
    with transaction.atomic():
        if not book.active:
            raise LibraryError("Este livro saiu do acervo.")
        if Loan.objects.filter(book=book, student=student, returned_at__isnull=True).exists():
            raise LibraryError(f"{student.first_name} já está com este livro.")
        if Reservation.objects.filter(book=book, student=student, status__in=Reservation.OPEN).exists():
            raise LibraryError(f"{student.first_name} já está na fila deste livro.")
        if available(book) > 0:
            raise LibraryError("Há exemplar livre: é só pegar na biblioteca.")
        r = Reservation.objects.create(school=book.school, book=book, student=student, created_by=user)
        create_audit_log(user=user, action="create", request=request, target=r,
                         detail=f"Reservou “{book.title}” para {student}")
    return r


def queue_position(reservation):
    if reservation.status != Reservation.Status.WAITING:
        return None
    return Reservation.objects.filter(book=reservation.book, status=Reservation.Status.WAITING).filter(
        Q(created_at__lt=reservation.created_at) | Q(created_at=reservation.created_at, pk__lt=reservation.pk)
    ).count() + 1


def cancel(reservation, user, request=None):
    was_ready = reservation.status == Reservation.Status.READY
    reservation.status = Reservation.Status.CANCELED
    reservation.save(update_fields=["status"])
    create_audit_log(user=user, action="update", request=request, target=reservation,
                     detail=f"Cancelou a reserva de “{reservation.book.title}” para {reservation.student}")
    if was_ready:
        promote(reservation.book)


def daily(today=None):
    """Rotina do dia: reservas não retiradas passam a vez, lembrete na véspera da devolução e aviso de atraso (no
    1º dia e depois a cada semana). Fora do ano letivo não manda lembrete."""
    from apps.school_calendar.services import in_school_year

    today = today or timezone.localdate()
    sent = 0
    for r in (Reservation.objects.filter(status=Reservation.Status.READY, expires_on__lt=today)
              .select_related("book", "book__school")):
        r.status = Reservation.Status.EXPIRED
        r.save(update_fields=["status"])
        promote(r.book, today)
    open_loans = Loan.objects.filter(returned_at__isnull=True, due_on__lte=today + timedelta(days=1)).select_related(
        "book", "student", "student__school")
    in_year = {}
    for loan in open_loans:
        school = loan.student.school
        if school.pk not in in_year:
            in_year[school.pk] = in_school_year(school, today)
        if not in_year[school.pk]:
            continue
        late = (today - loan.due_on).days
        if late == -1:
            sent += _notify(loan.student, f"Devolver amanhã: {loan.book.title}",
                            f"O livro da biblioteca vence em {loan.due_on:%d/%m/%Y}. Dá para renovar pela plataforma "
                            f"se ninguém estiver esperando por ele.", f"biblioteca:vence:{loan.pk}:{loan.due_on}")
        elif late == 1 or (late > 1 and late % 7 == 0):
            sent += _notify(loan.student, f"Livro atrasado: {loan.book.title}",
                            f"Venceu em {loan.due_on:%d/%m/%Y} ({late} dia(s)). Devolva na biblioteca: outros "
                            f"estudantes podem estar esperando.", f"biblioteca:atraso:{loan.pk}:{late}", high=True)
    return sent
