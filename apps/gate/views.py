"""Carteirinha (emissão, segunda via, impressão por turma, carteirinha digital) e portaria (leitura, painel
do dia, histórico e horários).

Quem faz o quê:

- **emitem e imprimem:** secretaria, direção e administração;
- **leem na portaria e acompanham o dia:** secretaria, coordenação (painel só das turmas da designação),
  direção e administração;
- **definem horários e tolerância:** direção e administração;
- **veem a carteirinha e o histórico de entradas:** a equipe acima, o responsável com vínculo aprovado e o
  próprio estudante.
"""

import datetime

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import ClassGroup
from apps.core.models import Role, create_audit_log
from apps.registry.models import Enrollment, Student

from . import services
from .models import GateEvent, GateSettings, StudentCard
from .symbols import code128_svg, qr_svg

ISSUERS = (Role.SECRETARIA.value, Role.DIRECAO.value, Role.ADMIN.value)
STATION = ISSUERS + (Role.COORDENACAO.value,)
SETTERS = (Role.DIRECAO.value, Role.ADMIN.value)


def _current_classes(school):
    """Turmas do ano letivo atual; sem ano marcado como atual, todas as da escola."""
    qs = ClassGroup.objects.filter(school=school)
    current = qs.filter(school_year__is_current=True)
    return (current if current.exists() else qs).order_by("name")


def _family_can_see(user, student):
    from apps.registry.access import is_own_record
    from apps.registry.models import GuardianLink

    if user.role == Role.RESPONSAVEL.value:
        return GuardianLink.objects.filter(guardian=user, student=student, status="aprovado").exists()
    return user.role == Role.ESTUDANTE.value and is_own_record(user, student)


def _student_for(user, student_id):
    student = get_object_or_404(Student, pk=student_id, school=user.school)
    if user.role in STATION or _family_can_see(user, student):
        return student
    raise PermissionDenied


def _card_context(card):
    cg = services.active_class(card.student)
    return {"card": card, "cg": cg, "qr": qr_svg(services.qr_payload(card), label="QR Code da carteirinha"),
            "barcode": code128_svg(card.code), "expired": card.valid_until < timezone.localdate()}


def mine(request):
    """Família e estudante: carteirinha e entradas de cada filho (ou do próprio estudante)."""
    from apps.registry.access import student_of
    from apps.registry.models import GuardianLink

    user = request.user
    if user.role == Role.RESPONSAVEL.value:
        students = [ln.student for ln in GuardianLink.objects.filter(guardian=user, status="aprovado")
                    .select_related("student").order_by("student__first_name")]
    elif user.role == Role.ESTUDANTE.value:
        own = student_of(user)
        students = [own] if own else []
    else:
        raise PermissionDenied
    cards = {c.student_id: c for c in StudentCard.objects.filter(student__in=students, revoked_at__isnull=True)}
    last = {}
    for e in GateEvent.objects.filter(student__in=students, kind=GateEvent.Kind.ENTRY).order_by("-at")[:50]:
        last.setdefault(e.student_id, e)
    return render(request, "gate/mine.html", {"rows": [{"student": s, "card": cards.get(s.pk), "last": last.get(s.pk)}
                                                      for s in students]})


def card_view(request, student_id):
    user = request.user
    student = _student_for(user, student_id)
    card = services.active_card(student)
    if card and user.role not in STATION:
        create_audit_log(user=user, action="view", request=request, target=card,
                         detail=f"Abriu a carteirinha digital de {student.full_name}")
    return render(request, "gate/card.html", {
        "student": student, "can_issue": user.role in ISSUERS, "is_staff": user.role in STATION,
        "revoked": StudentCard.objects.filter(student=student, revoked_at__isnull=False)[:5],
        **(_card_context(card) if card else {"card": None}),
    })


@require_POST
def card_issue(request, student_id):
    user = request.user
    if user.role not in ISSUERS:
        raise PermissionDenied
    student = get_object_or_404(Student, pk=student_id, school=user.school)
    second = services.active_card(student) is not None
    reason = (request.POST.get("motivo") or "").strip()
    if second and not reason:
        messages.error(request, "Informe o motivo da segunda via (perda, dano, troca de foto…).")
        return redirect("gate:card", student_id=student.pk)
    card = services.issue(student, user, reason)
    create_audit_log(user=user, action="create", request=request, target=card,
                     detail=f"{'Segunda via' if second else 'Emissão'} da carteirinha de {student.full_name}"
                            + (f": {reason}" if reason else ""))
    messages.success(request, "Segunda via emitida; a carteirinha anterior deixou de valer." if second
                     else "Carteirinha emitida.")
    return redirect("gate:card", student_id=student.pk)


def cards_index(request):
    """Turmas do ano com quantas carteirinhas faltam emitir."""
    user = request.user
    if user.role not in ISSUERS:
        raise PermissionDenied
    classes = list(_current_classes(user.school))
    active = set(StudentCard.objects.filter(school=user.school, revoked_at__isnull=True)
                 .values_list("student_id", flat=True))
    rows = []
    for cg in classes:
        ids = set(Enrollment.objects.filter(class_group=cg, status="ativo").values_list("student_id", flat=True))
        rows.append({"cg": cg, "total": len(ids), "with_card": len(ids & active), "missing": len(ids - active)})
    return render(request, "gate/cards_index.html", {"rows": rows})


def class_cards(request, class_id):
    """Situação das carteirinhas da turma, emissão das que faltam e impressão em lote."""
    user = request.user
    if user.role not in ISSUERS:
        raise PermissionDenied
    cg = get_object_or_404(ClassGroup, pk=class_id, school=user.school)
    students = sorted({e.student for e in Enrollment.objects.filter(class_group=cg, status="ativo")
                       .select_related("student")}, key=lambda s: s.full_name)
    if request.method == "POST":
        made = [services.issue(s, user) for s in students if services.active_card(s) is None]
        if made:
            create_audit_log(user=user, action="create", request=request, target=cg,
                             detail=f"Emitiu {len(made)} carteirinha(s) da turma {cg.name}")
        messages.success(request, f"{len(made)} carteirinha(s) emitida(s).")
        return redirect("gate:class_cards", class_id=cg.pk)
    cards = {c.student_id: c for c in StudentCard.objects.filter(student__in=students, revoked_at__isnull=True)}
    printing = request.GET.get("imprimir") == "1"
    rows = [{"student": s, "card": cards.get(s.pk), **(_card_context(cards[s.pk]) if printing and s.pk in cards
                                                      else {})} for s in students]
    return render(request, "gate/class_cards_print.html" if printing else "gate/class_cards.html", {
        "cg": cg, "rows": rows, "missing": sum(1 for r in rows if not r["card"]),
        "classes": ClassGroup.objects.filter(school=user.school, school_year__is_current=True).order_by("name"),
    })


def station(request):
    """Leitura da carteirinha: leitor USB (digita o código e Enter), câmera ou digitação."""
    user = request.user
    if user.role not in STATION:
        raise PermissionDenied
    ctx = {"kind": request.POST.get("tipo") or request.GET.get("tipo") or GateEvent.Kind.ENTRY}
    if ctx["kind"] not in GateEvent.Kind.values:
        ctx["kind"] = GateEvent.Kind.ENTRY
    if request.method == "POST":
        ctx.update(_read(request, user, ctx["kind"]))
    today = timezone.localdate()
    ctx["recent"] = GateEvent.objects.filter(school=user.school, day=today).select_related("student",
                                                                                          "class_group")[:8]
    ctx["manual_q"] = (request.GET.get("q") or "").strip()[:60]
    if ctx["manual_q"]:
        ctx["manual"] = Student.objects.filter(school=user.school, status="ativo").filter(
            Q(first_name__icontains=ctx["manual_q"]) | Q(last_name__icontains=ctx["manual_q"])).order_by(
            "first_name")[:10]
    return render(request, "gate/station.html", ctx)


def _read(request, user, kind):
    if request.POST.get("estudante", "").isdigit():  # registro manual, sem carteirinha
        student = get_object_or_404(Student, pk=int(request.POST["estudante"]), school=user.school)
        event, existed = services.register(student, kind, GateEvent.Method.MANUAL, user)
        return {"event": event, "existed": existed, "student": student}
    raw = request.POST.get("codigo", "")
    code, info = services.parse(raw)
    if code is None:
        _refused(request, user, info)
        return {"error": info}
    card = StudentCard.objects.filter(code=code, school=user.school).select_related("student").first()
    if card is None:
        _refused(request, user, "Código não encontrado nesta escola.")
        return {"error": "Código não encontrado nesta escola."}
    if not card.active:
        msg = (f"Carteirinha cancelada em {timezone.localtime(card.revoked_at):%d/%m/%Y}"
               f" ({card.revoked_reason}). Confira quem está com ela.")
        _refused(request, user, msg, card.student)
        return {"error": msg, "student": card.student}
    method = info or (GateEvent.Method.BARCODE if request.POST.get("origem") in ("leitor", "camera-barras")
                      else GateEvent.Method.CODE)
    event, existed = services.register(card.student, kind, method, user, card=card)
    return {"event": event, "existed": existed, "student": card.student,
            "expired": card.valid_until < timezone.localdate(), "no_class": event.class_group is None}


def _refused(request, user, reason, student=None):
    create_audit_log(user=user, action="reject", request=request, target=student,
                     detail=f"Portaria: leitura recusada. {reason}"[:250])


def today(request):
    """Painel do dia: chegadas, atrasos, saídas e quem ainda não chegou, por turma."""
    user = request.user
    if user.role not in STATION:
        raise PermissionDenied
    day = timezone.localdate()
    if (request.GET.get("dia") or "")[:10]:
        try:
            day = datetime.date.fromisoformat(request.GET["dia"][:10])
        except ValueError:
            pass
    classes = _current_classes(user.school)
    if user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import class_scope

        scope = class_scope(user)
        if scope is not None:
            classes = classes.filter(pk__in=scope)
    events = list(GateEvent.objects.filter(school=user.school, day=day, class_group__in=classes)
                  .select_related("student", "class_group").order_by("at"))
    entries = {e.student_id: e for e in events if e.kind == GateEvent.Kind.ENTRY}
    exits = {e.student_id for e in events if e.kind == GateEvent.Kind.EXIT}
    cfg = GateSettings.for_school(user.school)
    now = timezone.localtime()
    rows = []
    for cg in classes:
        studs = sorted({e.student for e in Enrollment.objects.filter(class_group=cg, status="ativo")
                        .select_related("student")}, key=lambda s: s.full_name)
        if not studs:
            continue
        arrived = [s for s in studs if s.pk in entries]
        expected = cfg.entry_for(cg.turn)
        started = day < now.date() or (day == now.date() and now.time() >= expected)
        rows.append({"cg": cg, "total": len(studs), "arrived": len(arrived), "expected": expected,
                     "late": [entries[s.pk] for s in arrived if entries[s.pk].late],
                     "missing": [s for s in studs if s.pk not in entries] if started else [],
                     "left": sum(1 for s in arrived if s.pk in exits)})
    return render(request, "gate/today.html", {
        "day": day, "rows": rows, "events": events, "cfg": cfg,
        "totals": {"arrived": len(entries), "late": sum(1 for e in entries.values() if e.late),
                   "left": len(exits)},
        "prev": day - datetime.timedelta(days=1), "next": day + datetime.timedelta(days=1),
        "is_today": day == timezone.localdate()})


def history(request, student_id):
    user = request.user
    student = _student_for(user, student_id)
    events = GateEvent.objects.filter(student=student).select_related("class_group")[:120]
    since = timezone.localdate() - datetime.timedelta(days=30)
    recent = [e for e in events if e.day >= since and e.kind == GateEvent.Kind.ENTRY]
    return render(request, "gate/history.html", {
        "student": student, "events": events, "is_staff": user.role in STATION,
        "late_30": sum(1 for e in recent if e.late), "entries_30": len(recent)})


class GateSettingsForm(forms.ModelForm):
    class Meta:
        model = GateSettings
        fields = ["entry_morning", "entry_afternoon", "entry_full", "entry_night", "tolerance", "fill_attendance"]
        widgets = {f: forms.TimeInput(format="%H:%M", attrs={"type": "time"})
                   for f in ("entry_morning", "entry_afternoon", "entry_full", "entry_night")}

    def clean_tolerance(self):
        value = self.cleaned_data["tolerance"]
        if value > 120:
            raise forms.ValidationError("Use no máximo 120 minutos.")
        return value


def settings_edit(request):
    user = request.user
    if user.role not in SETTERS:
        raise PermissionDenied
    cfg = GateSettings.for_school(user.school)
    form = GateSettingsForm(request.POST or None, instance=cfg)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.updated_by = user
        obj.save()
        create_audit_log(user=user, action="update", request=request, target=obj,
                         detail="Alterou os horários de entrada e a tolerância da portaria")
        messages.success(request, "Horários salvos.")
        return redirect("gate:today")
    return render(request, "gate/settings.html", {"form": form})
