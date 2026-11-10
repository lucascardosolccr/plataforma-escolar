"""Biblioteca escolar: acervo, balcão de empréstimos, "Meus livros" da família e regras. Quem pode o quê está em
``access``; as regras de cada operação, em ``services``."""

import csv
import io

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.models import create_audit_log
from apps.core.pagination import paginate
from apps.core.params import as_id, digits, name_q
from apps.registry.models import Student

from . import access, services
from .forms import BookForm, ImportForm, SettingsForm
from .models import Book, Loan, Reservation


def _need(ok):
    if not ok:
        raise PermissionDenied


def _book(user, pk):
    return get_object_or_404(Book, pk=pk, school=user.school)


def _back(request, fallback):
    """Volta para a tela de onde veio a ação, se for da plataforma."""
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else fallback)


def _out_count():
    """Exemplares fora da estante (emprestados + separados), por livro, numa subconsulta."""
    def sub(qs):
        return Coalesce(Subquery(qs.values("book").annotate(n=Count("pk")).values("n")), 0)

    return (sub(Loan.objects.filter(book=OuterRef("pk"), returned_at__isnull=True))
            + sub(Reservation.objects.filter(book=OuterRef("pk"), status=Reservation.Status.READY)))


def catalog(request):
    user = request.user
    _need(access.can_browse(user))
    operator = access.can_operate(user)
    qs = Book.objects.filter(school=user.school)
    if not operator or request.GET.get("baixados") != "1":
        qs = qs.filter(active=True)
    q = (request.GET.get("q") or "").strip()[:80]
    for term in q.split()[:5]:
        qs = qs.filter(Q(title__icontains=term) | Q(author__icontains=term) | Q(isbn__icontains=term))
    category = request.GET.get("tipo", "")
    if category in Book.Category.values:
        qs = qs.filter(category=category)
    if request.GET.get("livres") == "1":
        qs = qs.annotate(n_out=_out_count()).filter(copies__gt=F("n_out"))
    page = paginate(request, qs)
    stats = services.counts(list(page))
    rows = [{"b": b, "free": max(0, b.copies - stats[b.pk][0] - stats[b.pk][1]), "waiting": stats[b.pk][2]}
            for b in page]
    return render(request, "library/catalog.html", {
        "page": page, "rows": rows, "q": q, "category": category, "categories": Book.Category.choices,
        "operator": operator, "only_free": request.GET.get("livres") == "1",
        "mine": bool(access.own_students(user))})


def book_detail(request, pk):
    user = request.user
    _need(access.can_browse(user))
    book = _book(user, pk)
    operator = access.can_operate(user)
    if not book.active and not operator:
        raise PermissionDenied
    lent, held, waiting = services.counts([book])[book.pk]
    ctx = {"book": book, "free": max(0, book.copies - lent - held), "lent": lent, "held": held, "waiting": waiting,
           "operator": operator, "today": timezone.localdate()}
    kids = access.own_students(user)
    if kids:
        open_loans = {ln.student_id: ln for ln in Loan.objects.filter(book=book, student__in=kids,
                                                                      returned_at__isnull=True)}
        res = {r.student_id: r for r in Reservation.objects.filter(book=book, student__in=kids,
                                                                   status__in=Reservation.OPEN)}
        ctx["kids"] = [{"student": s, "loan": open_loans.get(s.pk), "reservation": res.get(s.pk),
                        "position": services.queue_position(res[s.pk]) if s.pk in res else None} for s in kids]
    if operator:
        ctx["loans"] = book.loans.filter(returned_at__isnull=True).select_related("student")
        ctx["queue"] = book.reservations.filter(status__in=Reservation.OPEN).select_related("student")
        ctx["times_lent"] = book.loans.count()
    return render(request, "library/book.html", ctx)


def book_form(request, pk=None):
    user = request.user
    _need(access.can_operate(user))
    book = _book(user, pk) if pk else None
    form = BookForm(request.POST or None, instance=book, school=user.school)
    if request.method == "POST" and form.is_valid():
        new = form.save(commit=False)
        if book is None:
            new.school, new.created_by = user.school, user
        new.save()
        create_audit_log(user=user, action="update" if book else "create", request=request, target=new,
                         detail=f"{'Editou' if book else 'Cadastrou'} o livro “{new.title}” ({new.copies} exemplar(es))")
        if book:
            services.promote(new)  # mais exemplares: a fila anda
        messages.success(request, "Livro salvo.")
        return redirect("library:book", pk=new.pk)
    return render(request, "library/book_form.html", {"form": form, "book": book})


def lend(request, pk):
    """Emprestar: procurar o estudante pelo nome ou código e confirmar."""
    user = request.user
    _need(access.can_operate(user))
    book = _book(user, pk)
    if request.method == "POST":
        student = get_object_or_404(Student, pk=as_id(request.POST.get("estudante")), school=user.school)
        try:
            loan = services.lend(book, student, user, request)
        except services.LibraryError as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"Emprestado a {student.full_name} até {loan.due_on:%d/%m/%Y}.")
            return redirect("library:book", pk=book.pk)
    q = (request.GET.get("q") or request.POST.get("q") or "").strip()[:60]
    found = []
    if q:
        qs = Student.objects.filter(school=user.school, status="ativo")
        qs = qs.filter(code=q) if digits(q) else qs.filter(name_q(q))
        found = list(qs.order_by("first_name", "last_name")[:20])
    held = book.reservations.filter(status=Reservation.Status.READY).select_related("student")
    stats = {}
    for row in (Loan.objects.filter(student__in=found, returned_at__isnull=True).values("student_id")
                .annotate(n=Count("pk"), late=Count("pk", filter=Q(due_on__lt=timezone.localdate())))):
        stats[row["student_id"]] = row
    classes = services.class_names(found)
    return render(request, "library/lend.html", {
        "book": book, "q": q, "found": [{"s": s, "cls": classes.get(s.pk, ""), "open": stats.get(s.pk, {}).get("n", 0),
                                         "late": stats.get(s.pk, {}).get("late", 0)} for s in found],
        "held": held, "free": services.available(book), "cfg": access.settings_for(user.school)})


def desk(request):
    """Balcão: quem está com livro, atrasos primeiro, livros separados para retirar e números do acervo."""
    user = request.user
    _need(access.can_operate(user))
    today = timezone.localdate()
    loans = Loan.objects.filter(school=user.school, returned_at__isnull=True).select_related("book", "student")
    q = (request.GET.get("q") or "").strip()[:60]
    if q:
        loans = loans.filter(Q(book__title__icontains=q) | name_q(q, "student__"))
    if request.GET.get("atrasados") == "1":
        loans = loans.filter(due_on__lt=today)
    year_start = today.replace(month=1, day=1)
    books = Book.objects.filter(school=user.school, active=True)
    return render(request, "library/desk.html", {
        "page": paginate(request, loans), "q": q, "only_late": request.GET.get("atrasados") == "1",
        "today": today,
        "ready": Reservation.objects.filter(school=user.school, status=Reservation.Status.READY)
        .select_related("book", "student").order_by("expires_on"),
        "n_titles": books.count(), "n_copies": sum(books.values_list("copies", flat=True)),
        "n_open": Loan.objects.filter(school=user.school, returned_at__isnull=True).count(),
        "n_late": Loan.objects.filter(school=user.school, returned_at__isnull=True, due_on__lt=today).count(),
        "top": Book.objects.filter(school=user.school, loans__lent_at__date__gte=year_start)
        .annotate(n=Count("loans")).order_by("-n", "title")[:5],
        "can_configure": access.can_configure(user)})


@require_POST
def give_back(request, pk):
    user = request.user
    _need(access.can_operate(user))
    loan = get_object_or_404(Loan, pk=pk, school=user.school)
    try:
        services.give_back(loan, user, (request.POST.get("estado") or "").strip(), request)
    except services.LibraryError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Devolução registrada: “{loan.book.title}”.")
    return _back(request, "library:desk")


@require_POST
def renew(request, pk):
    user = request.user
    loan = get_object_or_404(Loan, pk=pk, school=user.school)
    _need(access.can_act_for(user, loan.student))
    try:
        loan = services.renew(loan, user, request)
    except services.LibraryError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Renovado até {loan.due_on:%d/%m/%Y}.")
    return _back(request, "library:mine")


@require_POST
def reserve(request, pk):
    user = request.user
    book = _book(user, pk)
    student = get_object_or_404(Student, pk=as_id(request.POST.get("estudante")), school=user.school)
    _need(access.can_browse(user) and access.can_act_for(user, student))
    try:
        r = services.reserve(book, student, user, request)
    except services.LibraryError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"{student.first_name} entrou na fila (posição {services.queue_position(r)}). "
                                  f"Avisamos quando o livro estiver separado.")
    return redirect("library:book", pk=book.pk)


@require_POST
def cancel_reservation(request, pk):
    user = request.user
    r = get_object_or_404(Reservation, pk=pk, school=user.school, status__in=Reservation.OPEN)
    _need(access.can_act_for(user, r.student))
    services.cancel(r, user, request)
    messages.success(request, "Reserva cancelada.")
    return _back(request, "library:mine")


def mine(request):
    """Livros de cada filho (ou do próprio estudante): com quem está, até quando, fila e o que já leu."""
    user = request.user
    kids = access.own_students(user)
    _need(access.can_browse(user) and (kids or user.role in access.FAMILY))
    today = timezone.localdate()
    cfg = access.settings_for(user.school) if user.school_id else None
    rows = []
    for s in kids:
        res = list(s.book_reservations.filter(status__in=Reservation.OPEN).select_related("book"))
        rows.append({
            "student": s,
            "loans": [{"loan": ln, "late": ln.days_late(today)} for ln in
                      s.loans.filter(returned_at__isnull=True).select_related("book")],
            "reservations": [{"r": r, "position": services.queue_position(r)} for r in res],
            "history": s.loans.filter(returned_at__isnull=False).select_related("book").order_by("-returned_at")[:30],
            "n_read": s.loans.filter(returned_at__isnull=False).values("book").distinct().count(),
        })
    return render(request, "library/mine.html", {"rows": rows, "cfg": cfg, "today": today})


def settings_view(request):
    user = request.user
    _need(access.can_configure(user))
    cfg = access.settings_for(user.school)
    form = SettingsForm(request.POST or None, instance=cfg, school=user.school)
    if request.method == "POST" and form.is_valid():
        form.save()
        create_audit_log(user=user, action="update", request=request, target=cfg,
                         detail=f"Alterou as regras da biblioteca ({cfg.loan_days} dias, {cfg.max_loans} livro(s))")
        messages.success(request, "Regras da biblioteca salvas.")
        return redirect("library:desk")
    return render(request, "library/settings.html", {"form": form})


CATEGORY_BY_TEXT = {**{v: v for v in Book.Category.values},
                    **{label.split(" (")[0].lower(): v for v, label in Book.Category.choices},
                    "quadrinhos": "hq", "gibi": "hq", "manga": "hq", "mangá": "hq", "didático": "didatico",
                    "paradidático": "didatico", "dicionário": "referencia", "informativo": "informativo"}


def _read_rows(raw):
    text = None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("latin-1")  # nunca falha
    sample = text[:2000]
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    return list(csv.reader(io.StringIO(text), delimiter=delim))


def import_books(request):
    """Planilha do acervo (CSV). Repetir a importação não duplica: título e autor iguais são pulados."""
    user = request.user
    _need(access.can_operate(user))
    form = ImportForm(request.POST or None, request.FILES or None)
    report = None
    if request.method == "POST" and form.is_valid():
        f = form.cleaned_data["file"]
        if f.size > 2 * 1024 * 1024 or not f.name.lower().endswith((".csv", ".txt")):
            form.add_error("file", "Envie um arquivo .csv de até 2 MB (no Excel: Salvar como → CSV).")
        else:
            report = {"created": 0, "skipped": 0, "errors": []}
            rows = _read_rows(f.read())
            if rows and rows[0] and rows[0][0].strip().lower() in ("título", "titulo", "title"):
                rows = rows[1:]
            existing = {(t.lower(), a.lower()) for t, a in
                        Book.objects.filter(school=user.school).values_list("title", "author")}
            for n, row in enumerate(rows[:3000], start=2):
                cells = [c.strip() for c in row] + [""] * 8
                title, author = " ".join(cells[0].split())[:200], cells[1][:150]
                if not title:
                    continue
                if (title.lower(), author.lower()) in existing:
                    report["skipped"] += 1
                    continue
                copies = int(cells[2]) if digits(cells[2]) and 1 <= int(cells[2]) <= 500 else None
                year = int(cells[6]) if digits(cells[6]) and 1450 <= int(cells[6]) <= 2100 else None
                if cells[2] and copies is None:
                    report["errors"].append(f"Linha {n}: exemplares “{cells[2][:10]}” não é um número de 1 a 500.")
                    continue
                Book.objects.create(school=user.school, title=title, author=author, copies=copies or 1,
                                    category=CATEGORY_BY_TEXT.get(cells[3].lower(), Book.Category.OTHER),
                                    location=cells[4][:60], publisher=cells[5][:100], year=year,
                                    isbn=cells[7][:20], created_by=user)
                existing.add((title.lower(), author.lower()))
                report["created"] += 1
            create_audit_log(user=user, action="create", request=request, target=None,
                             detail=f"Importou {report['created']} livro(s) para a biblioteca "
                                    f"({report['skipped']} já existiam)")
    return render(request, "library/import.html", {"form": form, "report": report})
