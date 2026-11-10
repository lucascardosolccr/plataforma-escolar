"""Atendimentos de saúde na escola: registro pela equipe ou pelo professor, aviso imediato à família e "ciente".

Quem vê está em ``access.can_view_incident``. A lista geral é da equipe (coordenação: só as turmas da designação);
o professor vê os que registrou; a família, os dos filhos.
"""

import datetime

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.models import Role, create_audit_log
from apps.core.pagination import paginate
from apps.core.params import digits, name_q
from apps.registry.models import Student

from . import access
from .models import HealthIncident, HealthRecord

#: Orientação que acompanha o aviso quando o estudante bateu a cabeça (o mesmo que a escola diria por telefone).
HEAD_ADVICE = ("Bateu a cabeça: nas próximas 24 horas, observe sonolência fora do normal, vômito, dor de cabeça forte, "
               "confusão ou dificuldade para andar ou falar. Se aparecer algum desses sinais, procure atendimento médico.")


class IncidentForm(forms.ModelForm):
    class Meta:
        model = HealthIncident
        fields = ["happened_at", "kind", "place", "description", "head_hit", "care_given", "phone_contact", "outcome"]
        widgets = {"happened_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
                   "description": forms.Textarea(attrs={"rows": 3}), "care_given": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["happened_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        if not self.is_bound:
            self.initial.setdefault("happened_at", timezone.localtime().strftime("%Y-%m-%dT%H:%M"))

    def clean_happened_at(self):
        when = self.cleaned_data["happened_at"]
        now = timezone.now()
        if when > now + datetime.timedelta(minutes=5):
            raise forms.ValidationError("Não pode ser no futuro.")
        if when < now - datetime.timedelta(days=7):
            raise forms.ValidationError("Registre em até 7 dias. Para algo mais antigo, use as ocorrências.")
        return when


def _reachable_students(user):
    qs = Student.objects.filter(school=user.school, status="ativo")
    if user.role in access.OFFICE:
        return qs
    if user.role == Role.PROFESSOR.value:
        from apps.academics.permissions import teacher_class_ids

        return qs.filter(enrollments__class_group__in=teacher_class_ids(user), enrollments__status="ativo").distinct()
    if user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import class_scope

        scope = class_scope(user)
        return qs if scope is None else qs.filter(enrollments__class_group__in=scope,
                                                  enrollments__status="ativo").distinct()
    return qs.none()


def incident_pick(request):
    """Escolher o estudante para registrar um atendimento."""
    user = request.user
    if not user.school_id or (user.role not in access.TEAM and user.role != Role.PROFESSOR.value):
        raise PermissionDenied
    q = (request.GET.get("q") or "").strip()[:60]
    found = []
    if q:
        qs = _reachable_students(user)
        found = list((qs.filter(code=q) if digits(q) else qs.filter(name_q(q))).order_by("first_name", "last_name")[:15])
        from apps.library.services import class_names

        classes = class_names(found)
        found = [{"s": s, "cls": classes.get(s.pk, "")} for s in found]
    return render(request, "care/incident_pick.html", {"q": q, "found": found})


def incident_create(request, student_id):
    user = request.user
    student = get_object_or_404(Student, pk=student_id, school=user.school) if user.school_id else None
    if not student or not access.can_register_incident(user, student):
        raise PermissionDenied
    form = IncidentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        inc = form.save(commit=False)
        inc.school, inc.student, inc.registered_by = user.school, student, user
        inc.save()
        create_audit_log(user=user, action="create", request=request, target=inc,
                         detail=f"Registrou atendimento de saúde de {student}: {inc.get_kind_display()}")
        n = _tell_family(inc)
        messages.success(request, "Atendimento registrado." + (" A família foi avisada." if n else
                                                                " Nenhum responsável com conta: avise por telefone."))
        return redirect("care:incident", pk=inc.pk)
    record = HealthRecord.objects.filter(student=student).first()
    return render(request, "care/incident_form.html", {"form": form, "student": student, "record": record,
                                                       "full": access.health_level(user, student) == "full"})


def _tell_family(inc):
    from apps.communication.family_events import notify_family
    from apps.communication.models import Notification

    s = inc.student
    when = timezone.localtime(inc.happened_at)
    urgent = inc.outcome in HealthIncident.URGENT
    title = (f"Urgente: {s.first_name} — {inc.get_outcome_display().lower()}" if urgent
             else f"Atendimento na escola: {s.first_name}")
    body = f"{s.first_name} foi atendido(a) na escola às {when:%H:%M} ({inc.get_kind_display().lower()}). " \
           f"Desfecho: {inc.get_outcome_display().lower()}. Veja o que aconteceu e o que foi feito, e marque ciente."
    if inc.head_hit:
        body += " " + HEAD_ADVICE
    return notify_family(s, "atendimento_saude", title, body=body, url=reverse("care:incident", args=[inc.pk]),
                         include_student=False, dedupe_key=f"atendimento:{inc.pk}",
                         priority=Notification.Priority.HIGH)


def incident_detail(request, pk):
    user = request.user
    inc = get_object_or_404(HealthIncident.objects.select_related("student", "registered_by", "acknowledged_by"),
                            pk=pk, school=user.school) if user.school_id else None
    if not inc or not access.can_view_incident(user, inc):
        raise PermissionDenied
    family = user.role == Role.RESPONSAVEL.value
    if not family:
        create_audit_log(user=user, action="view", request=request, target=inc,
                         detail=f"Consultou o atendimento de saúde de {inc.student}")
    return render(request, "care/incident_detail.html", {"inc": inc, "family": family, "head_advice": HEAD_ADVICE})


@require_POST
def incident_ack(request, pk):
    from apps.registry.access import guardian_of

    user = request.user
    inc = get_object_or_404(HealthIncident.objects.select_related("student"), pk=pk, school=user.school)
    if not guardian_of(user, inc.student):
        raise PermissionDenied
    if not inc.acknowledged_at:
        inc.acknowledged_by, inc.acknowledged_at = user, timezone.now()
        inc.family_note = (request.POST.get("recado") or "").strip()[:300]
        inc.save(update_fields=["acknowledged_by", "acknowledged_at", "family_note"])
        create_audit_log(user=user, action="update", request=request, target=inc,
                         detail=f"Ciente do atendimento de saúde de {inc.student}")
        if inc.family_note and inc.registered_by:
            from apps.communication.models import Notification
            from apps.communication.services import notify_many

            notify_many(inc.school, [inc.registered_by], Notification.Kind.HEALTH,
                        f"Recado da família de {inc.student.first_name} sobre o atendimento",
                        body=inc.family_note, url=reverse("care:incident", args=[inc.pk]),
                        dedupe_key=f"atendimento:recado:{inc.pk}")
    messages.success(request, "Obrigado. A escola sabe que você viu.")
    return redirect("care:incident", pk=inc.pk)


def incident_list(request):
    user = request.user
    if not user.school_id:
        raise PermissionDenied
    qs = HealthIncident.objects.filter(school=user.school).select_related("student", "registered_by")
    if user.role == Role.RESPONSAVEL.value:
        from .views import _children

        qs = qs.filter(student__in=_children(user))
    elif user.role in access.TEAM:
        if user.role == Role.COORDENACAO.value:
            qs = qs.filter(student__in=_reachable_students(user))
    elif user.role == Role.PROFESSOR.value:
        qs = qs.filter(registered_by=user)
    else:
        raise PermissionDenied
    kind = request.GET.get("tipo", "")
    if kind in HealthIncident.Kind.values:
        qs = qs.filter(kind=kind)
    return render(request, "care/incidents.html", {
        "page": paginate(request, qs), "kind": kind, "kinds": HealthIncident.Kind.choices,
        "family": user.role == Role.RESPONSAVEL.value,
        "can_register": user.role in access.TEAM or user.role == Role.PROFESSOR.value})


def pending_acks(user):
    """Atendimentos dos filhos nos últimos 7 dias ainda sem "ciente"."""
    from .views import _children

    since = timezone.now() - datetime.timedelta(days=7)
    return HealthIncident.objects.filter(student__in=_children(user), acknowledged_at__isnull=True,
                                         happened_at__gte=since).count()
