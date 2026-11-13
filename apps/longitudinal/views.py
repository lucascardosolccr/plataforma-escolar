"""Telas da trajetória escolar. Regras de acesso em ``access``; cálculos em ``timeline``, ``diagnosis``,
``cohort`` e ``forecast``."""

import csv
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import ClassGroup, SchoolYear
from apps.analytics import charts
from apps.analytics.views import _csv_safe
from apps.cognitio.models import ModelRun
from apps.core.models import Role, create_audit_log
from apps.core.pagination import paginate
from apps.core.params import as_id
from apps.registry.importer import ImportFileError
from apps.registry.models import Enrollment, GuardianLink, Student

from . import access, cohort, diagnosis, forecast, importer
from . import stages as st
from . import timeline as tl
from .models import Outcome, PriorGrade, PriorYear, YearResult


# ------------------------------------------------------------------ página do estudante

def _student(request, student_id):
    student = get_object_or_404(Student.objects.select_related("school"), pk=student_id)
    if request.user.school_id and student.school_id != request.user.school_id:
        raise Http404
    if not access.can_view_timeline(request.user, student):
        raise PermissionDenied
    return student


def _charts(rows):
    with_avg = [r for r in rows if r["average"] is not None]
    with_att = [r for r in rows if r["attendance"] is not None]
    avg = charts.line_chart([{"label": f"{r['year']}{'*' if r['in_progress'] else ''}", "value": r["average"]}
                             for r in with_avg], y_min=0, y_max=10) if len(with_avg) >= 2 else None
    att = charts.line_chart([{"label": f"{r['year']}{'*' if r['in_progress'] else ''}", "value": r["attendance"]}
                             for r in with_att], y_min=0, y_max=100, suffix="%") if len(with_att) >= 2 else None
    return avg, att


def _subject_matrix(rows):
    """Componentes nas linhas, anos nas colunas (nome comum entre escolas e anos)."""
    years = [r["year"] for r in rows]
    keys = sorted({s["key"] for r in rows for s in r["subjects"]})
    matrix = []
    for k in keys:
        cells = []
        for r in rows:
            s = next((s for s in r["subjects"] if s["key"] == k), None)
            cells.append(s)
        matrix.append({"key": k, "cells": cells})
    return years, matrix


def student_page(request, student_id):
    student = _student(request, student_id)
    user = request.user
    rows = tl.build(student)
    ctx = {"student": student, "rows": rows, "can_edit": access.can_edit_history(user, student),
           "can_diagnose": access.can_view_diagnosis(user, student), "today": timezone.localdate()}
    ctx["chart_avg"], ctx["chart_att"] = _charts(rows)
    ctx["years"], ctx["matrix"] = _subject_matrix(rows)
    if ctx["can_diagnose"]:
        ctx["findings"] = diagnosis.diagnose(rows)
        current = next((r for r in reversed(rows) if r["in_progress"]), None)
        ctx["needed"] = tl.needed_grades(current) if current else []
        run = forecast.active_run(student.school)
        ctx["run"] = run
        ctx["prediction"] = forecast.predict_for(rows, run)
    create_audit_log(user=user, action="view", request=request, target=student,
                     detail=f"Consultou a trajetória escolar de {student.full_name}")
    return render(request, "longitudinal/student.html", ctx)


# ------------------------------------------------------------------ anos anteriores

class PriorYearForm(forms.ModelForm):
    grades_text = forms.CharField(
        label="Notas finais", required=False, widget=forms.Textarea(attrs={"rows": 8}),
        help_text="Uma por linha, como no histórico: “Matemática: 7,5”. Conceito também vale: “Arte: B”.")
    scale = forms.DecimalField(label="Nota máxima da escala", initial=Decimal("10"), min_value=Decimal("1"),
                               max_value=Decimal("1000"), decimal_places=2, localize=True,
                               help_text="10 na maioria das escolas; 100 se o histórico usa 0 a 100.")

    class Meta:
        model = PriorYear
        fields = ["year", "grade_label", "school_name", "outcome", "attendance_percent", "passing_grade", "notes"]
        localized_fields = ["attendance_percent", "passing_grade"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            grades = list(self.instance.grades.all())
            if grades:
                self.fields["scale"].initial = grades[0].scale_max
            self.fields["grades_text"].initial = "\n".join(
                f"{g.subject}: {g.concept or str(g.value).replace('.', ',')}" for g in grades)

    def clean_grades_text(self):
        out, errors = [], []
        for n, line in enumerate((self.cleaned_data.get("grades_text") or "").splitlines(), start=1):
            if not line.strip():
                continue
            if ":" not in line:
                errors.append(f"Linha {n}: use “Componente: nota”.")
                continue
            subject, raw = (p.strip() for p in line.rsplit(":", 1))
            if not subject or not raw:
                errors.append(f"Linha {n}: falta o componente ou a nota.")
                continue
            out.append((subject[:80], raw))
        if len({s.lower() for s, _ in out}) != len(out):
            errors.append("Há componente repetido.")
        if errors:
            raise forms.ValidationError(errors)
        return out

    def clean(self):
        data = super().clean()
        scale = data.get("scale") or Decimal("10")
        parsed = []
        for subject, raw in data.get("grades_text") or []:
            value = importer.parse_number(raw)
            if value is None:
                parsed.append((subject, None, raw[:12]))
            elif not 0 <= value <= scale:
                self.add_error("grades_text", f"{subject}: {raw} está fora da escala de 0 a {scale.normalize()}.")
            else:
                parsed.append((subject, value, ""))
        data["parsed"] = parsed
        return data


def prior_form(request, student_id, pk=None):
    student = _student(request, student_id)
    if not access.can_edit_history(request.user, student):
        raise PermissionDenied
    instance = get_object_or_404(PriorYear, pk=pk, student=student) if pk else None
    form = PriorYearForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.student, obj.school = student, student.school
        obj.stage = st.parse_stage(obj.grade_label)
        if not obj.pk:
            obj.created_by = request.user
        if PriorYear.objects.filter(student=student, year=obj.year, school_name=obj.school_name).exclude(
                pk=obj.pk).exists():
            form.add_error("year", "Já há um registro deste estudante neste ano e nesta escola.")
        else:
            obj.save()
            obj.grades.all().delete()
            scale = form.cleaned_data.get("scale") or Decimal("10")
            PriorGrade.objects.bulk_create([PriorGrade(record=obj, subject=s, value=v, concept=c, scale_max=scale)
                                            for s, v, c in form.cleaned_data["parsed"]])
            create_audit_log(user=request.user, action="update" if instance else "create", request=request,
                             target=student, detail=f"Ano anterior {obj.year} ({obj.grade_label}) de {student.full_name}")
            messages.success(request, f"Ano {obj.year} salvo na trajetória de {student.first_name}.")
            return redirect("longitudinal:student", student.pk)
    return render(request, "longitudinal/prior_form.html", {"form": form, "student": student, "obj": instance})


@require_POST
def prior_delete(request, pk):
    obj = get_object_or_404(PriorYear.objects.select_related("student"), pk=pk)
    if not access.can_edit_history(request.user, obj.student):
        raise PermissionDenied
    student = obj.student
    create_audit_log(user=request.user, action="delete", request=request, target=student,
                     detail=f"Excluiu o ano anterior {obj.year} ({obj.grade_label}) de {student.full_name}")
    obj.delete()
    messages.success(request, "Ano anterior excluído.")
    return redirect("longitudinal:student", student.pk)


# ------------------------------------------------------------------ importação

def import_view(request):
    if not access.can_edit_history(request.user):
        raise PermissionDenied
    school = request.user.school
    ctx = {"headers": importer.TEMPLATE_HEADERS}
    if request.method == "POST":
        try:
            if request.POST.get("dados"):
                matrix = importer.unseal(request.POST["dados"])
                rows, _ = importer.validate(school, matrix)
                created, updated = importer.apply(school, rows, request.user)
                skipped = sum(1 for r in rows if r["errors"])
                create_audit_log(user=request.user, action="import", request=request,
                                 detail=f"Importou anos anteriores: {created} novos, {updated} atualizados, "
                                        f"{skipped} com erro")
                messages.success(request, f"{created} ano(s) anterior(es) importado(s), {updated} atualizado(s)"
                                          + (f"; {skipped} linha(s) com erro ficaram de fora." if skipped else "."))
                return redirect("longitudinal:index")
            upload = request.FILES.get("arquivo")
            if not upload:
                raise ImportFileError("Escolha a planilha.")
            matrix = importer.read_matrix(upload)
            rows, warnings = importer.validate(school, matrix)
            ctx.update({"rows": rows, "warnings": warnings, "token": importer.seal(matrix),
                        "ok": sum(1 for r in rows if not r["errors"]), "bad": sum(1 for r in rows if r["errors"])})
        except ImportFileError as exc:
            messages.error(request, str(exc))
    return render(request, "longitudinal/import.html", ctx)


def import_template(request):
    if not access.can_edit_history(request.user):
        raise PermissionDenied
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="modelo-anos-anteriores.csv"'
    resp.write("﻿")
    w = csv.writer(resp, delimiter=";")
    w.writerow(importer.TEMPLATE_HEADERS)
    w.writerow(["123", "", "", "2025", "3º ano", "EC 10 de Ceilândia", "Aprovado", "94,5", "7,5", "6,8", "8",
                "7", "7,2", "9", "10", "8"])
    return resp


# ------------------------------------------------------------------ resultado final do ano

def _closing_years(school):
    return SchoolYear.objects.filter(school=school).order_by("-name")


def results(request):
    if not access.can_record_results(request.user):
        raise PermissionDenied
    school = request.user.school
    years = list(_closing_years(school))
    year = next((y for y in years if str(y.pk) == request.GET.get("ano")), None) or \
        next((y for y in years if y.is_current), None) or (years[0] if years else None)
    classes = []
    if year:
        recorded = {}
        for cg_id, n in (YearResult.objects.filter(enrollment__school_year=year)
                         .values_list("enrollment__class_group_id", "pk")):
            recorded[cg_id] = recorded.get(cg_id, 0) + 1
        for c in ClassGroup.objects.filter(school=school, school_year=year).order_by("name"):
            total = Enrollment.objects.filter(class_group=c).exclude(status="transferido").count()
            classes.append({"c": c, "total": total, "done": recorded.get(c.pk, 0)})
    return render(request, "longitudinal/results.html", {
        "years_options": [(y.pk, y.name) for y in years], "year": year, "classes": classes})


def results_class(request, class_id):
    if not access.can_record_results(request.user):
        raise PermissionDenied
    cg = get_object_or_404(ClassGroup, pk=class_id, school=request.user.school)
    enrollments = list(Enrollment.objects.filter(class_group=cg).select_related("student")
                       .order_by("student__first_name", "student__last_name"))
    timelines = tl.build_many(cg.school, [e.student for e in enrollments])
    existing = {r.enrollment_id: r for r in YearResult.objects.filter(enrollment__in=enrollments)}
    items = []
    for e in enrollments:
        row = next((r for r in timelines[e.student_id] if r.get("school_year") == cg.school_year), None)
        suggestion = Outcome.UNKNOWN
        if e.status == "transferido":
            suggestion = Outcome.TRANSFERRED
        elif e.status == "desistente":
            suggestion = Outcome.DROPOUT
        elif row and row["subjects"] and not row["n_below"] and (row["attendance"] is None
                                                               or row["attendance"] >= row["min_attendance"]):
            suggestion = Outcome.APPROVED
        items.append({"e": e, "row": row, "current": existing.get(e.pk), "suggestion": suggestion})
    if request.method == "POST":
        valid = set(Outcome.values) - {Outcome.UNKNOWN}
        saved = 0
        for it in items:
            value = request.POST.get(f"r-{it['e'].pk}", "")
            if value in valid:
                YearResult.objects.update_or_create(
                    enrollment=it["e"], defaults={"school": cg.school, "outcome": value, "decided_by": request.user,
                                                  "note": request.POST.get(f"n-{it['e'].pk}", "")[:300]})
                saved += 1
            elif value == "" and it["current"]:
                it["current"].delete()
        create_audit_log(user=request.user, action="update", request=request, target=cg,
                         detail=f"Resultado final do ano: {saved} estudante(s) de {cg}")
        messages.success(request, f"Resultado final salvo para {saved} estudante(s) de {cg.name}.")
        return redirect(f"{request.path}")
    return render(request, "longitudinal/results_class.html", {
        "cg": cg, "items": items, "outcomes": [(v, label) for v, label in Outcome.choices if v != Outcome.UNKNOWN]})


# ------------------------------------------------------------------ painel da escola

def _children(user):
    if user.role == Role.RESPONSAVEL.value:
        ids = GuardianLink.objects.filter(guardian=user, status="aprovado").values_list("student_id", flat=True)
        return list(Student.objects.filter(pk__in=ids))
    own = getattr(user, "student_record", None) if user.role == Role.ESTUDANTE.value else None
    return [own] if own else []


def _signal_rows(timelines, students, run):
    out = []
    for s in students:
        rows = timelines[s.pk]
        if not rows:
            continue
        cur = next((r for r in reversed(rows) if r["in_progress"]), None)
        if cur is None:
            continue
        found = [f for f in diagnosis.diagnose(rows) if f.level == "atencao"]
        pred = forecast.predict_for(rows, run) if run else None
        out.append({"s": s, "row": cur, "findings": found, "prediction": pred,
                    "years": sum(1 for r in rows if not r["in_progress"])})
    out.sort(key=lambda d: (-(d["prediction"]["probability"] if d["prediction"] else 0), -len(d["findings"]),
                            d["s"].first_name))
    return out


def index(request):
    user = request.user
    if user.role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value):
        return render(request, "longitudinal/family.html", {"children": _children(user)})
    if not (access.is_analyst(user) or access.can_edit_history(user)):
        raise PermissionDenied
    school = user.school
    ids = access.scope_ids(user)
    ctx = {"is_analyst": access.is_analyst(user), "can_edit": access.can_edit_history(user),
           "can_results": access.can_record_results(user), "scoped": ids is not None}
    if not ctx["is_analyst"]:
        # Secretaria e administração veem só a cobertura: sem montar a trajetória de cada estudante.
        years = set(PriorYear.objects.filter(school=school).values_list("year", flat=True))
        years |= {tl.year_number(y) for y in SchoolYear.objects.filter(school=school, enrollments__isnull=False)}
        years.discard(None)
        ctx["coverage"] = {"students": Student.objects.filter(school=school).count(),
                           "with_prior": PriorYear.objects.filter(school=school).values("student").distinct().count(),
                           "years": [(y, None) for y in sorted(years)]}
        return render(request, "longitudinal/index.html", ctx)
    students = list(tl.students_of(school, ids).order_by("first_name", "last_name"))
    timelines = tl.build_many(school, students)
    ctx["coverage"] = cohort.coverage(timelines)
    if ctx["is_analyst"]:
        run = forecast.active_run(school)
        classes = ClassGroup.objects.filter(school=school, school_year__is_current=True).order_by("name")
        class_id = as_id(request.GET.get("turma"))
        signal = _signal_rows(timelines, students, run)
        if class_id:
            signal = [d for d in signal if d["row"].get("class_group") and str(d["row"]["class_group"].pk) == class_id]
        if request.GET.get("todos") != "1":
            signal = [d for d in signal if d["findings"] or d["prediction"]]
        ctx.update({
            "flow": cohort.flow_rates(timelines), "distortion": cohort.distortion_by_stage(timelines),
            "retention": cohort.survival_curve(timelines),
            "transitions": cohort.transitions(timelines), "signals": cohort.signal_validation(timelines),
            "stability": cohort.stability(timelines), "run": run, "latest": forecast.runs(school).first(),
            "page": paginate(request, signal), "classes": [(c.pk, c.name) for c in classes],
            "class_id": class_id or "", "show_all": request.GET.get("todos") == "1",
        })
    return render(request, "longitudinal/index.html", ctx)


def export_csv(request):
    user = request.user
    if not access.is_analyst(user):
        raise PermissionDenied
    school = user.school
    students = list(tl.students_of(school, access.scope_ids(user)).order_by("first_name", "last_name"))
    timelines = tl.build_many(school, students)
    run = forecast.active_run(school)
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="trajetoria-sinais.csv"'
    resp.write("﻿")
    w = csv.writer(resp, delimiter=";")
    w.writerow(["Estudante", "Turma", "Anos no histórico", "Sinais que pedem atenção", "Previsão (%)"])
    for d in _signal_rows(timelines, students, run):
        cg = d["row"].get("class_group")
        w.writerow([_csv_safe(d["s"].full_name), _csv_safe(cg.name if cg else d["row"]["grade_label"]), d["years"],
                    _csv_safe("; ".join(f.title for f in d["findings"])),
                    str(round(100 * d["prediction"]["probability"])) if d["prediction"] else ""])
    create_audit_log(user=user, action="export", request=request, detail="Exportou os sinais da trajetória escolar")
    return resp


# ------------------------------------------------------------------ modelo de previsão

def model_page(request):
    user = request.user
    if not access.is_analyst(user):
        raise PermissionDenied
    school = user.school
    if request.method == "POST":
        action = request.POST.get("acao")
        if action == "treinar":
            if not access.can_train(user):
                raise PermissionDenied
            r = forecast.run(school, user=user)
            create_audit_log(user=user, action="create", request=request,
                             detail=f"Validou o modelo de previsão da trajetória ({r.get_status_display()})")
            messages.success(request, "Validação concluída. Veja o resultado abaixo.")
        elif action in ("aprovar", "desativar"):
            if not access.can_approve(user):
                raise PermissionDenied
            r = get_object_or_404(ModelRun, pk=as_id(request.POST.get("execucao")), school=school, name=forecast.NAME)
            if action == "aprovar":
                if r.status != ModelRun.Status.EXPERIMENTAL or not r.metrics.get("approvable"):
                    messages.error(request, "Só uma validação que passou em todos os critérios técnicos pode ser aprovada.")
                    return redirect("longitudinal:model")
                forecast.runs(school).filter(status=ModelRun.Status.APPROVED).update(
                    status=ModelRun.Status.DISABLED, decided_by=user, decided_at=timezone.now())
                r.status = ModelRun.Status.APPROVED
            else:
                r.status = ModelRun.Status.DISABLED
            r.decided_by, r.decided_at = user, timezone.now()
            r.save(update_fields=["status", "decided_by", "decided_at"])
            create_audit_log(user=user, action="update", request=request,
                             detail=f"{'Aprovou' if action == 'aprovar' else 'Desativou'} o uso do modelo de previsão "
                                    f"da trajetória (validação {r.pk})")
            messages.success(request, "Decisão registrada.")
        return redirect("longitudinal:model")
    runs = list(forecast.runs(school)[:10])
    latest = runs[0] if runs else None
    labels = dict(forecast.FEATURES)
    coefs = []
    if latest and latest.coefficients.get("coefs"):
        coefs = sorted(({"label": labels.get(k, k), "coef": c, "odds": 2.718281828 ** c}
                        for k, c in zip(latest.coefficients["features"], latest.coefficients["coefs"])),
                       key=lambda d: -abs(d["coef"]))
    return render(request, "longitudinal/model.html", {
        "runs": runs, "latest": latest, "coefs": coefs, "active": forecast.active_run(school),
        "can_train": access.can_train(user), "can_approve": access.can_approve(user),
        "criteria": {"epv": forecast.EPV, "n_features": len(forecast.FEATURES), "min_test": forecast.MIN_TEST,
                     "min_each": forecast.MIN_TEST_EACH, "auc": forecast.MIN_AUC, "auc_low": forecast.MIN_AUC_LOW,
                     "slope": forecast.CAL_SLOPE},
    })
