"""Designação da coordenação (pela direção), painel e registros do coordenador."""

from datetime import timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import ClassGroup, Subject
from apps.core.models import Role, User, create_audit_log
from apps.core.pagination import paginate

from .models import CoordinationRecord, CoordinatorAssignment
from .scope import active_designations, class_scope, student_ids, teacher_scope

DATE = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})
DESIGNATORS = (Role.DIRECAO.value, Role.ADMIN.value)


def can_designate(user):
    return user.is_authenticated and user.role in DESIGNATORS


class DesignationForm(forms.ModelForm):
    class Meta:
        model = CoordinatorAssignment
        fields = ["coordinator", "area", "all_school", "class_groups", "subjects", "teachers",
                  "starts_on", "ends_on", "notes"]
        widgets = {"class_groups": forms.CheckboxSelectMultiple, "subjects": forms.CheckboxSelectMultiple,
                   "teachers": forms.CheckboxSelectMultiple, "starts_on": DATE, "ends_on": DATE}
        help_texts = {"all_school": "Marcado: acompanha todas as turmas (as listas abaixo são ignoradas)."}

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["coordinator"].queryset = User.objects.filter(
            school=school, role=Role.COORDENACAO.value, is_active=True).order_by("first_name")
        self.fields["class_groups"].queryset = ClassGroup.objects.filter(school=school).order_by("name")
        current = list(self.instance.subjects.values_list("pk", flat=True)) if self.instance.pk else []
        self.fields["subjects"].queryset = (Subject.choices_for(school)
                                            | Subject.objects.filter(school=school, pk__in=current)).distinct()
        self.fields["teachers"].queryset = User.objects.filter(
            school=school, role=Role.PROFESSOR.value, is_active=True).order_by("first_name")
        self.fields["starts_on"].initial = timezone.localdate()

    def clean(self):
        data = super().clean()
        if not data.get("all_school") and not (data.get("class_groups") or data.get("subjects")
                                               or data.get("teachers")):
            raise forms.ValidationError("Escolha turmas, disciplinas ou professores, ou marque “escola toda”.")
        s, e = data.get("starts_on"), data.get("ends_on")
        if s and e and e < s:
            self.add_error("ends_on", "O término não pode ser antes do início.")
        return data


def designation_list(request):
    if not can_designate(request.user):
        raise PermissionDenied
    school = request.user.school
    edit = None
    if (request.GET.get("editar") or "").isdigit():
        edit = get_object_or_404(CoordinatorAssignment, pk=request.GET["editar"], school=school)
    form = DesignationForm(request.POST or None, instance=edit, school=school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.school = school
            obj.created_by = obj.created_by or request.user
            obj.save()
            form.save_m2m()
            create_audit_log(user=request.user, action="update" if edit else "create", request=request, target=obj,
                             detail=f"{'Alterou' if edit else 'Criou'} a designação de coordenação de {obj.coordinator}: "
                                    + ("escola toda" if obj.all_school else
                                       f"{obj.class_groups.count()} turma(s), {obj.subjects.count()} disciplina(s), "
                                       f"{obj.teachers.count()} professor(es)"))
        messages.success(request, "Designação salva. O acesso do coordenador já segue a nova definição.")
        return redirect("coordination:designations")
    today = timezone.localdate()
    designations = CoordinatorAssignment.objects.filter(school=school).select_related("coordinator") \
        .prefetch_related("class_groups", "subjects", "teachers")
    without = User.objects.filter(school=school, role=Role.COORDENACAO.value, is_active=True).exclude(
        pk__in=[d.coordinator_id for d in designations
                if d.starts_on <= today and (d.ends_on is None or d.ends_on >= today)])
    return render(request, "coordination/designations.html", {
        "form": form, "edit": edit, "designations": designations, "today": today, "without": without,
    })


@require_POST
def designation_end(request, pk):
    if not can_designate(request.user):
        raise PermissionDenied
    d = get_object_or_404(CoordinatorAssignment, pk=pk, school=request.user.school)
    d.ends_on = timezone.localdate() - timedelta(days=1) if d.starts_on < timezone.localdate() \
        else d.starts_on
    d.save(update_fields=["ends_on"])
    create_audit_log(user=request.user, action="update", request=request, target=d,
                     detail=f"Encerrou a designação de coordenação de {d.coordinator}")
    messages.success(request, "Designação encerrada. O histórico continua registrado.")
    return redirect("coordination:designations")


# --------------------------------------------------------------------------
# Painel do coordenador


class RecordForm(forms.ModelForm):
    class Meta:
        model = CoordinationRecord
        fields = ["kind", "date", "title", "teacher", "class_group", "participants", "notes", "follow_up_on"]
        widgets = {"date": DATE, "follow_up_on": DATE, "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        school = user.school
        classes = ClassGroup.objects.filter(school=school).order_by("name")
        teachers = User.objects.filter(school=school, role=Role.PROFESSOR.value, is_active=True).order_by("first_name")
        scope, tscope = class_scope(user), teacher_scope(user)
        if scope is not None:
            classes = classes.filter(pk__in=scope)
        if tscope is not None:
            teachers = teachers.filter(pk__in=tscope)
        self.fields["class_group"].queryset = classes
        self.fields["teacher"].queryset = teachers
        self.fields["date"].initial = timezone.localdate()


def _can_use_panel(user):
    return user.is_authenticated and user.role in (Role.COORDENACAO.value, Role.DIRECAO.value)


def panel(request):
    user = request.user
    if not _can_use_panel(user):
        raise PermissionDenied
    from apps.analytics import bi
    from apps.pedagogy.models import InterventionPlan, PedagogicalObservation
    from apps.registry.models import Enrollment
    from apps.school_calendar.services import events_for_user

    school = user.school
    scope = class_scope(user)
    designations = list(active_designations(user).prefetch_related("class_groups", "subjects", "teachers")) \
        if user.role == Role.COORDENACAO.value else []
    no_designation = user.role == Role.COORDENACAO.value and not designations
    classes = ClassGroup.objects.filter(school=school).select_related("school_year")
    current_year = classes.filter(school_year__is_current=True)
    classes = (current_year if current_year.exists() else classes)
    if scope is not None:
        classes = classes.filter(pk__in=scope)
    classes = list(classes.order_by("name"))
    teachers = teacher_scope(user)
    sids = student_ids(user)
    students_count = (len(sids) if sids is not None else
                      Enrollment.objects.filter(school=school, status="ativo").values("student").distinct().count())
    period = bi.resolve_period(request.GET, school)
    class_rows, alerts = [], []
    for cg in classes[:15]:  # custo: um relatório por turma
        r = bi.class_report(cg, period)
        class_rows.append({"cg": cg, "active": r["active"], "mean": r["overall"]["mean"],
                           "attendance": r["attendance"]["percent"], "delivery": r["delivery_rate"],
                           "follow": len(r["follow_up"])})
        for row in r["follow_up"][:3]:
            alerts.append({"student": row["student"], "cg": cg, "reasons": row["reasons"]})
    obs = PedagogicalObservation.objects.filter(school=school).select_related("student", "teacher", "subject")
    plans = InterventionPlan.objects.filter(school=school, status=InterventionPlan.Status.ACTIVE) \
        .select_related("student")
    records = CoordinationRecord.objects.filter(school=school).select_related("teacher", "class_group")
    if sids is not None:
        obs = obs.filter(student_id__in=sids)
        plans = plans.filter(student_id__in=sids)
        records = records.filter(Q(class_group_id__in=scope) | Q(teacher_id__in=teachers or [])
                                 | Q(created_by=user))
    today = timezone.localdate()
    upcoming = [e for e in events_for_user(user, today, today + timedelta(days=30))
                if e.kind in ("reuniao", "conselho", "planejamento", "evento")][:5]
    from apps.pedagogy.views_planning import _visible_qs, week_coverage

    from .print_hooks import pending_print_requests

    form = RecordForm(user=user)
    return render(request, "coordination/panel.html", {
        "designations": designations, "no_designation": no_designation, "class_rows": class_rows,
        "classes_total": len(classes), "teachers_count": len(teachers) if teachers is not None else
        User.objects.filter(school=school, role=Role.PROFESSOR.value, is_active=True).count(),
        "students_count": students_count, "alerts": alerts[:12], "observations": obs.order_by("-observed_at")[:6],
        "plans": plans.order_by("-created_at")[:6], "records": records[:8],
        "follow_ups": records.filter(follow_up_on__isnull=False, follow_up_on__gte=today).order_by("follow_up_on")[:5],
        "upcoming": upcoming, "period": period, "presets": bi.PRESETS, "form": form,
        "prints": pending_print_requests(user)[:6],
        "plans_waiting": _visible_qs(user).filter(status="enviado").count(),
        "coverage": week_coverage(user),
        "support_items": _support_items(user, today),
    })


def _support_items(user, today):
    """Fila do apoio à inclusão (mesma contagem da central de pendências)."""
    from apps.core.pending import _support_team

    return _support_team(user, today)


def record_list(request):
    user = request.user
    if not _can_use_panel(user):
        raise PermissionDenied
    form = RecordForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        rec = form.save(commit=False)
        scope = class_scope(user)
        if scope is not None and rec.class_group_id and rec.class_group_id not in scope:
            raise PermissionDenied
        rec.school, rec.created_by = user.school, user
        rec.save()
        create_audit_log(user=user, action="create", request=request, target=rec, detail=f"Registrou: {rec}")
        messages.success(request, "Registro salvo.")
        return redirect("coordination:panel" if request.POST.get("voltar") == "painel" else "coordination:records")
    qs = CoordinationRecord.objects.filter(school=user.school).select_related("teacher", "class_group", "created_by")
    scope = class_scope(user)
    if scope is not None:
        teachers = teacher_scope(user) or set()
        qs = qs.filter(Q(class_group_id__in=scope) | Q(teacher_id__in=teachers) | Q(created_by=user))
    kind = request.GET.get("tipo", "")
    if kind in dict(CoordinationRecord.Kind.choices):
        qs = qs.filter(kind=kind)
    page = paginate(request, qs)
    return render(request, "coordination/records.html", {
        "form": form, "records": page, "page": page, "kind": kind, "kinds": CoordinationRecord.Kind.choices,
    })
