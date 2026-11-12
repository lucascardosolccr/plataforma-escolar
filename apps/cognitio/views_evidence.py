"""Registro de evidências: questões da avaliação, resultado por questão e observação direta."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.academics.models import ClassGroup, Subject
from apps.core.models import create_audit_log
from apps.core.params import as_id, digits
from apps.registry.models import Enrollment

from . import access
from .evidence import _grade_max, rebuild_class
from .forms import ObservationForm, QuestionForm
from .models import Question, QuestionResponse, QuestionSkill, SkillObservation
from .taxonomy import error_choices


def _evaluation_for_teacher(user, pk):
    from apps.pedagogy.models import Evaluation

    ev = get_object_or_404(Evaluation.objects.select_related("class_group", "subject"), pk=pk, school=user.school)
    if not access.can_teach(user, ev.class_group, ev.subject):
        raise PermissionDenied
    return ev


def _students(class_group, on_date=None):
    enr = Enrollment.objects.filter(class_group=class_group).select_related("student")
    out = [e.student for e in enr if e.status == "ativo" or (on_date and e.covers(on_date))]
    return sorted({s.pk: s for s in out}.values(), key=lambda s: s.first_name)


def questions(request, evaluation_id):
    """Questões da avaliação e as habilidades de cada uma."""
    user = request.user
    ev = _evaluation_for_teacher(user, evaluation_id)
    edit_id = request.GET.get("editar") or request.POST.get("question_id")
    instance = get_object_or_404(Question, pk=as_id(edit_id), evaluation=ev) if edit_id else None
    if request.method == "POST" and request.POST.get("_delete") and instance:
        n = instance.number
        instance.delete()
        create_audit_log(user=user, action="delete", request=request, target=ev,
                         detail=f"Excluiu a questão {n} de {ev.title}")
        messages.success(request, f"Questão {n} excluída.")
        return redirect("cognitio:questions", evaluation_id=ev.pk)
    form = QuestionForm(request.POST or None, instance=instance, evaluation=ev)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            q = form.save(commit=False)
            q.evaluation = ev
            q.save()
            QuestionSkill.objects.filter(question=q).delete()
            QuestionSkill.objects.create(question=q, item=form.cleaned_data["main_skill"], role="principal")
            for it in form.cleaned_data["secondary_codes"]:
                if it.pk != form.cleaned_data["main_skill"].pk:
                    QuestionSkill.objects.get_or_create(question=q, item=it, defaults={"role": "secundaria"})
            ev.curriculum.add(form.cleaned_data["main_skill"], *form.cleaned_data["secondary_codes"])
            create_audit_log(user=user, action="update" if instance else "create", request=request, target=ev,
                             detail=f"{'Atualizou' if instance else 'Criou'} a questão {q.number} de {ev.title}")
        messages.success(request, "Questão salva.")
        return redirect("cognitio:questions", evaluation_id=ev.pk)
    qs = list(ev.questions.prefetch_related("questionskill_set__item"))
    from apps.curriculum.models import component_for, year_for

    from .blueprint import blueprint_check
    from .nlp import suggest_skills

    basis = " ".join([ev.title, ev.description] + [q.label + " " + q.criteria for q in qs])
    suggestions = suggest_skills(basis, user.school, component_for(ev.subject), year_for(ev.class_group))
    return render(request, "cognitio/questions.html", {
        "ev": ev, "questions": qs, "form": form, "editing": instance, "suggestions": suggestions,
        "total": sum((q.max_points for q in qs), Decimal("0")), "blueprint": blueprint_check(ev, qs),
    })


def responses(request, evaluation_id):
    """Grade estudante × questão: pontos, situação e tipo de erro."""
    user = request.user
    ev = _evaluation_for_teacher(user, evaluation_id)
    qs = list(ev.questions.prefetch_related("questionskill_set__item"))
    if not qs:
        messages.info(request, "Cadastre as questões antes de lançar os resultados.")
        return redirect("cognitio:questions", evaluation_id=ev.pk)
    students = _students(ev.class_group, ev.date)
    existing = {(r.question_id, r.student_id): r for r in QuestionResponse.objects.filter(question__in=qs)}
    from apps.curriculum.models import component_for

    errors_opts = error_choices(component_for(ev.subject) or ev.subject.name)
    if request.method == "POST":
        problems, saved = [], 0
        statuses = dict(QuestionResponse.Status.choices)
        valid_errors = {c for c, _ in errors_opts}
        with transaction.atomic():
            for st in students:
                for q in qs:
                    key = f"{q.pk}_{st.pk}"
                    status = request.POST.get(f"s_{key}", "")
                    raw = (request.POST.get(f"p_{key}", "") or "").strip().replace(",", ".")
                    if not status and not raw:
                        continue
                    status = status if status in statuses else QuestionResponse.Status.ANSWERED
                    points = None
                    if status == QuestionResponse.Status.ANSWERED:
                        try:
                            points = Decimal(raw)
                        except InvalidOperation:
                            problems.append(f"{st.first_name} (Q{q.number})")
                            continue
                        if points < 0 or points > q.max_points:
                            problems.append(f"{st.first_name} (Q{q.number})")
                            continue
                    err = request.POST.get(f"e_{key}", "")
                    QuestionResponse.objects.update_or_create(question=q, student=st, defaults={
                        "status": status, "points": points, "error_type": err if err in valid_errors else "",
                        "updated_by": user})
                    saved += 1
            if request.POST.get("atualizar_notas") and ev.status == ev.Status.DRAFT:
                _grades_from_questions(ev, qs, students, user)
            create_audit_log(user=user, action="update", request=request, target=ev,
                             detail=f"Lançou resultados por questão em {ev.title} ({saved} registros)")
        rebuild_class(ev.class_group)
        if problems:
            messages.warning(request, "Pontuação inválida (fora de 0 a máximo da questão): " + ", ".join(problems[:10]))
        messages.success(request, f"{saved} resultado(s) salvos. As evidências por habilidade foram atualizadas.")
        return redirect("cognitio:responses", evaluation_id=ev.pk)
    rows = []
    for st in students:
        cells = []
        for q in qs:
            r = existing.get((q.pk, st.pk))
            cells.append({"q": q, "r": r, "key": f"{q.pk}_{st.pk}",
                          "points": "" if not r or r.points is None else f"{r.points.normalize():f}".replace(".", ",")})
        rows.append({"student": st, "cells": cells})
    return render(request, "cognitio/responses.html", {
        "ev": ev, "questions": qs, "rows": rows, "status_choices": QuestionResponse.Status.choices,
        "error_choices": errors_opts, "can_update_grades": ev.status == ev.Status.DRAFT,
    })


def _grades_from_questions(ev, qs, students, user):
    """Nota da avaliação = soma dos pontos, proporcional à nota máxima da disciplina.

    Só para quem respondeu ao menos uma questão; ausente em todas fica sem nota.
    """
    from apps.pedagogy.models import Grade

    total = sum((q.max_points for q in qs), Decimal("0"))
    top = _grade_max(ev.school, ev.subject)
    by_student = {}
    for r in QuestionResponse.objects.filter(question__in=qs):
        if r.status == QuestionResponse.Status.ANSWERED and r.points is not None:
            by_student[r.student_id] = by_student.get(r.student_id, Decimal("0")) + r.points
        elif r.status == QuestionResponse.Status.BLANK:
            by_student.setdefault(r.student_id, Decimal("0"))
    for st in students:
        if st.pk in by_student and total:
            value = (by_student[st.pk] / total * top).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            Grade.objects.update_or_create(evaluation=ev, student=st, school=ev.school,
                                           defaults={"value": value, "updated_by": user})


def observation_create(request, class_id, subject_id):
    """Observação direta do professor, para um ou vários estudantes de uma vez."""
    user = request.user
    cg = get_object_or_404(ClassGroup, pk=class_id, school=user.school)
    subject = get_object_or_404(Subject, pk=subject_id, school=user.school)
    if not access.can_teach(user, cg, subject):
        raise PermissionDenied
    students = _students(cg)
    form = ObservationForm(request.POST or None, pair=(cg, subject), students=students,
                           initial={"observed_on": timezone.localdate(), "item": request.GET.get("item")})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        own = 0
        with transaction.atomic():
            for sid in d["students"]:
                level = form.level_for(sid)
                own += level != d["level"]
                SkillObservation.objects.create(
                    school=user.school, student_id=int(sid), item=d["item"], class_group=cg, subject=subject,
                    teacher=user, observed_on=d["observed_on"], level=level, context=d["context"],
                    note=d["note"], activity=d.get("activity"), evaluation=d.get("evaluation"),
                    recheck_on=d.get("recheck_on"))
            create_audit_log(user=user, action="create", request=request, target=cg,
                             detail=f"Registrou observação de {d['item'].code} para {len(d['students'])} estudante(s)"
                                    + (f", {own} com nível próprio" if own else ""))
        rebuild_class(cg)
        messages.success(request, "Observação registrada como evidência.")
        return redirect(f"{_class_url(cg)}?disciplina={subject.pk}&habilidade={d['item'].pk}")
    rows = _observation_rows(form, students, request)
    levels = [
        ("Dificuldade observada", "Nesta situação, ainda não conseguiu realizar a tarefa da habilidade, mesmo com apoio."),
        ("Em desenvolvimento inicial", "Realizou partes da tarefa, com muito apoio ou com erros frequentes."),
        ("Em desenvolvimento", "Acertos parciais: realizou a tarefa com algum apoio ou com erros pontuais."),
        ("Em consolidação", "Realizou a tarefa quase sempre sem apoio; ainda oscila em situações novas."),
        ("Consolidada na situação observada", "Realizou com autonomia e consistência nesta situação."),
    ]
    return render(request, "cognitio/observation_form.html",
                  {"form": form, "cg": cg, "subject": subject, "levels": levels, **rows})


def _observation_rows(form, students, request):
    """Uma linha por estudante: marcado?, nível próprio e situação atual na habilidade.

    A situação mostra quem ainda não tem registro suficiente (Prompt 18 §7: "indicação
    clara do que ainda precisa ser registrado"). Uma consulta para as evidências de
    todos e uma para as decisões do professor.
    """
    from .gaps import item_state, judgments_for
    from .mastery import STATES
    from .models import MasteryScale, SkillEvidence

    raw = request.POST.get("item") or request.GET.get("item") or ""
    item = form.fields["item"].queryset.filter(pk=int(raw)).first() if digits(raw) else None
    chosen = set(request.POST.getlist("students")) if request.method == "POST" else set(request.GET.getlist("estudante"))
    states = {}
    if item is not None:
        scale = MasteryScale.for_school(request.user.school)
        evs = {}
        for e in SkillEvidence.objects.filter(item=item, student__in=students).order_by("observed_on"):
            evs.setdefault(e.student_id, []).append(e)
        judged = judgments_for([s.pk for s in students], [item.pk])
        for s in students:
            a = item_state(s, item, scale, evidences=evs.get(s.pk, []), judgment=judged.get((s.pk, item.pk)))
            state = getattr(a, "effective", a.state)
            states[s.pk] = (state, STATES[state][0])
    rows = [{"s": s, "checked": str(s.pk) in chosen, "lv": form[f"lv_{s.pk}"], "state": states.get(s.pk)}
            for s in students]
    missing = sum(1 for st in states.values() if st[0] in ("nao_avaliado", "insuficiente"))
    return {"rows": rows, "state_item": item, "missing": missing, "item_choices": list(form.fields["item"].queryset)}


def _class_url(cg):
    from django.urls import reverse

    return reverse("cognitio:class_view", args=[cg.pk])



def analysis(request, evaluation_id):
    """Depois da prova: o que ela mostrou, por habilidade e por questão (Prompt 18 §10.10).

    Professor do par, coordenação no alcance e direção. Fora o professor da turma, a
    consulta fica na auditoria, como a do mapa individual: a tela traz nomes.
    """
    from apps.pedagogy.models import Evaluation

    from .exam_analysis import LEVELS, analyze

    user = request.user
    ev = get_object_or_404(Evaluation.objects.select_related("class_group", "subject"), pk=evaluation_id,
                           school=user.school)
    subjects = access.class_subjects(user, ev.class_group)
    if subjects is not None and ev.subject_id not in subjects:
        raise PermissionDenied
    teacher = access.can_teach(user, ev.class_group, ev.subject)
    if not teacher:
        create_audit_log(user=user, action="view", request=request, target=ev,
                         detail=f"Consultou a análise da prova {ev.title} ({ev.class_group})")
    data = analyze(ev, _students(ev.class_group, ev.date), user.school)
    return render(request, "cognitio/exam_analysis.html", {
        "ev": ev, "a": data, "levels": LEVELS, "teacher": teacher,
        "guides": list(ev.study_guides.exclude(status="arquivado")),
    })
