"""Transforma registros que já existem na plataforma em evidências por habilidade.

O professor não registra nada duas vezes: questões, notas, entregas e
observações viram ``SkillEvidence`` automaticamente. ``rebuild_class`` é
idempotente (atualiza o que mudou e remove o que deixou de existir) e é chamado
depois de cada lançamento; ``manage.py cognitio_rebuild`` refaz tudo.

Pesos (escolha metodológica documentada, configurável no código):
- questão ligada à habilidade principal: 1,0; secundária: 0,5;
- observação direta do professor: 1,0;
- produção escrita com análise revisada: 0,8;
- atividade de casa com nota: 0,7 (feita fora da sala, autoria menos certa);
- nota global de avaliação sem questões: 0,5 (não é granular);
- trabalho em grupo: 0,4 (produto coletivo).
"""

from decimal import Decimal

from .models import QuestionResponse, SkillEvidence, SkillObservation

W_MAIN, W_SECONDARY, W_OBS, W_TEXT, W_ACTIVITY, W_EVAL, W_GROUP = 1.0, 0.5, 1.0, 0.8, 0.7, 0.5, 0.4


def _grade_max(school, subject):
    from apps.pedagogy.models import AcademicRule

    rule = AcademicRule.objects.filter(school=school, subject=subject).first()
    passing = rule.passing_grade if rule else Decimal("6.0")
    return Decimal("10") if passing <= 10 else Decimal("100")


def _clip(x):
    return max(0.0, min(1.0, float(x)))


def _collect_class(class_group):
    """Gera os dicionários de evidência da turma (sem gravar)."""
    from apps.pedagogy.models import Activity, Evaluation, GroupWork, GroupWorkDelivery, Submission
    from apps.registry.models import Enrollment

    school = class_group.school
    student_ids = set(Enrollment.objects.filter(class_group=class_group).values_list("student_id", flat=True))
    rows = []

    def add(student_id, item_id, source, sid, label, day, ratio, weight, subject_id, error="", reason=""):
        rows.append({"school_id": school.pk, "student_id": student_id, "item_id": item_id, "source_type": source,
                     "source_id": sid, "source_label": label[:200], "class_group_id": class_group.pk,
                     "subject_id": subject_id, "observed_on": day, "ratio": ratio, "weight": weight,
                     "error_type": error, "no_evidence_reason": reason})

    evals = Evaluation.objects.filter(class_group=class_group).prefetch_related("questions__questionskill_set",
                                                                                "curriculum")
    for ev in evals:
        questions = list(ev.questions.all())
        if questions:
            responses = QuestionResponse.objects.filter(question__in=questions).select_related("question")
            for r in responses:
                q = r.question
                for qs in q.questionskill_set.all():
                    weight = W_MAIN if qs.role == "principal" else W_SECONDARY
                    label = f"{ev.title} — Q{q.number}"
                    if r.status == QuestionResponse.Status.ANSWERED and r.points is not None and q.max_points:
                        add(r.student_id, qs.item_id, "questao", r.pk, label, ev.date,
                            _clip(r.points / q.max_points), weight, ev.subject_id, r.error_type)
                    elif r.status in (QuestionResponse.Status.BLANK, QuestionResponse.Status.ABSENT):
                        add(r.student_id, qs.item_id, "questao", r.pk, label, ev.date,
                            None, 0.0, ev.subject_id, reason=r.get_status_display().lower())
            continue
        items = list(ev.curriculum.all())
        if not items or ev.status != Evaluation.Status.PUBLISHED:
            continue
        top = _grade_max(school, ev.subject)
        for g in ev.grades.filter(value__isnull=False):
            for it in items:
                add(g.student_id, it.pk, "avaliacao", g.pk, f"{ev.title} (nota geral)", ev.date,
                    _clip(g.value / top), W_EVAL, ev.subject_id)

    for act in Activity.objects.filter(class_group=class_group, status=Activity.Status.PUBLISHED).prefetch_related(
            "curriculum"):
        items = list(act.curriculum.all())
        if not items:
            continue
        top = _grade_max(school, act.subject)
        for sub in Submission.objects.filter(activity=act):
            day = act.deadline or act.class_date or act.published_date
            for it in items:
                if sub.grade is not None:
                    add(sub.student_id, it.pk, "atividade", sub.pk, act.title, day, _clip(sub.grade / top),
                        W_ACTIVITY, act.subject_id)
                elif sub.status in ("nao_entregue",):
                    add(sub.student_id, it.pk, "atividade", sub.pk, act.title, day, None, 0.0, act.subject_id,
                        reason="não entregue")

    for work in GroupWork.objects.filter(class_group=class_group, status=GroupWork.Status.PUBLISHED).prefetch_related(
            "curriculum", "groups__members"):
        items = list(work.curriculum.all())
        if not items:
            continue
        top = _grade_max(school, work.subject)
        for d in GroupWorkDelivery.objects.filter(group_work=work, grade__isnull=False).select_related("group"):
            members = [d.student_id] if d.student_id else [m.student_id for m in d.group.members.all()
                                                          if m.removed_at is None]
            for sid in members:
                for it in items:
                    add(sid, it.pk, "trabalho", d.pk, f"{work.title} (grupo)",
                        d.delivered_at or work.deadline or work.published_date, _clip(d.grade / top), W_GROUP,
                        work.subject_id)

    for o in SkillObservation.objects.filter(class_group=class_group):
        add(o.student_id, o.item_id, "observacao", o.pk, f"Observação: {o.context}", o.observed_on,
            SkillObservation.RATIO[o.level], W_OBS, o.subject_id)

    from .models import TextAnalysis

    for a in TextAnalysis.objects.filter(class_group=class_group, reviewed=True).exclude(teacher_level__isnull=True):
        for it in a.items.all():
            add(a.student_id, it.pk, "texto", a.pk, f"Produção escrita: {a.title}", a.produced_on,
                SkillObservation.RATIO[a.teacher_level], W_TEXT, a.subject_id)
    return [r for r in rows if r["student_id"] in student_ids]


def rebuild_class(class_group):
    """Sincroniza ``SkillEvidence`` da turma. Devolve (criadas/atualizadas, removidas)."""
    rows = _collect_class(class_group)
    keep = set()
    changed = 0
    existing = {(e.student_id, e.item_id, e.source_type, e.source_id): e
                for e in SkillEvidence.objects.filter(class_group=class_group)}
    for r in rows:
        key = (r["student_id"], r["item_id"], r["source_type"], r["source_id"])
        keep.add(key)
        e = existing.get(key)
        fields = {k: v for k, v in r.items() if k not in ("student_id", "item_id", "source_type", "source_id")}
        if e is None:
            SkillEvidence.objects.create(**r)
            changed += 1
        elif any(getattr(e, k) != v for k, v in fields.items()):
            for k, v in fields.items():
                setattr(e, k, v)
            e.save()
            changed += 1
    stale = [e.pk for k, e in existing.items() if k not in keep]
    SkillEvidence.objects.filter(pk__in=stale).delete()
    return changed, len(stale)


def rebuild_school(school):
    from apps.academics.models import ClassGroup

    total = [0, 0]
    for cg in ClassGroup.objects.filter(school=school):
        a, b = rebuild_class(cg)
        total[0] += a
        total[1] += b
    return tuple(total)
