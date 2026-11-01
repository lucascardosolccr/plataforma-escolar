"""Progresso das metas da escola, com as fórmulas do painel institucional.

- Frequência, média geral e entregas vêm de ``bi.institutional_report`` (escola toda) ou da linha da
  turma no mesmo relatório. Turma com menos de ``bi.SMALL_GROUP`` estudantes não tem valor, pela mesma
  proteção de grupos pequenos dos painéis.
- Habilidades: entre os pares estudante+habilidade com evidência no período, a parte em
  "consolidada" ou "em consolidação" (EIA-Cognitio, regras explícitas).
Sem dado, o valor é ``None`` ("sem dados"), nunca zero.
"""

from django.utils import timezone

from . import bi
from .models import SchoolGoal

UNITS = {"frequencia": "%", "media_geral": "", "entregas": "%", "habilidades": "%"}


def _skills_share(school, class_group, start, end):
    from apps.cognitio.mastery import assess, group_evidence
    from apps.cognitio.models import MasteryScale, SkillEvidence

    evs = SkillEvidence.objects.filter(school=school, observed_on__gte=start, observed_on__lte=end)
    if class_group is not None:
        evs = evs.filter(class_group=class_group)
    groups = group_evidence(evs)
    if not groups:
        return None
    scale = MasteryScale.for_school(school)
    states = [assess(e, scale, today=end).state for e in groups.values()]
    judged = [s for s in states if s not in ("insuficiente", "nao_avaliado")]
    if not judged:
        return None
    return bi.pct(sum(1 for s in judged if s in ("consolidada", "consolidacao")), len(judged))


def current_value(goal, today=None):
    today = today or timezone.localdate()
    end = min(today, goal.deadline)
    if end < goal.starts_on:
        return None
    if goal.indicator == SchoolGoal.Indicator.SKILLS:
        return _skills_share(goal.school, goal.class_group, goal.starts_on, end)
    period = bi.Period(goal.starts_on, end, "personalizado", "")
    report = bi.institutional_report(goal.school, period)
    if goal.class_group_id:
        row = next((r for r in report["classes"] if r["class_group"].pk == goal.class_group_id), None)
        if row is None:
            return None
        source = row
    else:
        source = {"attendance": report["attendance"], "average": report["overall"]["mean"],
                  "delivery_rate": report["delivery_rate"]}
    key = {"frequencia": "attendance", "media_geral": "average", "entregas": "delivery_rate"}[goal.indicator]
    return source.get(key)


def progress(goal, today=None):
    """Valor atual, situação e o que falta. A situação é sempre calculada, nunca digitada."""
    today = today or timezone.localdate()
    value = current_value(goal, today)
    target = float(goal.target)
    finished = today > goal.deadline
    if value is None:
        status, label = "sem_dados", "Sem dados ainda" if not finished else "Sem dados no período"
    elif value >= target:
        status, label = "atingida", "Meta atingida" if finished else "No alvo até agora"
    elif finished:
        status, label = "nao_atingida", "Não atingida no prazo"
    else:
        status, label = "abaixo", "Abaixo da meta até agora"
    return {"goal": goal, "value": value, "target": target, "unit": UNITS[goal.indicator],
            "status": status, "label": label, "gap": None if value is None else round(target - value, 2),
            "days_left": (goal.deadline - today).days if not finished else None, "finished": finished}


def goals_for(school, include_inactive=False):
    qs = SchoolGoal.objects.filter(school=school).select_related("class_group")
    return qs if include_inactive else qs.filter(active=True)
