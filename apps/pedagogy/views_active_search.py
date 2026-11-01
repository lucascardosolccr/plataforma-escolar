"""Telas da busca ativa (ver ``active_search``). Direção, secretaria e coordenação (no seu escopo).
Família, professor e estudante não acessam: a relação reúne dados sensíveis de menores."""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.models import create_audit_log
from apps.registry.models import Student

from . import active_search as svc
from .models import AbsenceJustification, ActiveSearchAction, AttendanceRecord


class ActionForm(forms.ModelForm):
    class Meta:
        model = ActiveSearchAction
        fields = ["date", "kind", "outcome"]
        widgets = {"date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
                   "outcome": forms.Textarea(attrs={"rows": 3})}

    def clean_date(self):
        d = self.cleaned_data["date"]
        if d > timezone.localdate():
            raise forms.ValidationError("A data não pode ser futura: registre a ação depois de feita.")
        return d


def active_search(request):
    user = request.user
    if not svc.can_use(user):
        raise PermissionDenied
    data = svc.overview(user)
    create_audit_log(user=user, action="view", request=request,
                     detail=f"Consultou a busca ativa ({len(data['notify'])} para notificar, "
                            f"{len(data['attention'])} em atenção)")
    return render(request, "pedagogy/active_search.html", {"data": data})


def active_search_student(request, student_id):
    user = request.user
    student = get_object_or_404(Student, pk=student_id, school=user.school)
    if not svc.reaches(user, student):
        raise PermissionDenied
    form = ActionForm(request.POST or None, initial={"date": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            action = form.save(commit=False)
            action.school, action.student, action.recorded_by = user.school, student, user
            action.save()
            create_audit_log(user=user, action="create", request=request, target=student,
                             detail=f"Registrou na busca ativa: {action.get_kind_display()} ({action.date:%d/%m/%Y})")
        messages.success(request, "Ação registrada.")
        return redirect("pedagogy:active_search_student", student_id=student.pk)
    n_days, source, year = svc.school_days_in_year(user.school)
    limit = svc.limit_for(n_days)
    start = year.start_date if year and year.start_date else timezone.localdate().replace(month=1, day=1)
    records = list(AttendanceRecord.objects.filter(student=student, date__gte=start).select_related("class_group")
                   .order_by("-date"))
    ranges = [(j.start_date, j.end_date) for j in AbsenceJustification.objects.filter(
        student=student, status=AbsenceJustification.Status.APPROVED)]
    actions = list(student.active_search_actions.filter(date__gte=start).select_related("recorded_by"))
    situation = svc.student_situation(student, [(r.date, r.status) for r in records], ranges, actions)
    absences = [{"date": r.date, "class_group": r.class_group, "justified": any(a <= r.date <= b for a, b in ranges)}
                for r in records if r.status == AttendanceRecord.Status.ABSENT]
    create_audit_log(user=user, action="view", request=request, target=student,
                     detail=f"Consultou a busca ativa de {student}")
    return render(request, "pedagogy/active_search_student.html", {
        "student": student, "situation": situation, "absences": absences, "actions": actions, "form": form,
        "limit": limit, "limit_display": f"{limit:g}".replace(".", ","), "n_days": n_days, "source": source,
        "over": situation["absences"] > limit})
