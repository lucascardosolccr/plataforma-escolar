"""Telas de trajetória acadêmica e indicadores precoces (``trajectory.py``) e da validação local deles
(``ews_validation.py``).

Acesso igual ao do mapa da turma e do estudante no EIA-Cognitio. O professor vê as notas só das próprias
disciplinas. Ocorrências entram só para quem pode vê-las. Família e estudante não acessam: indicadores
são para a equipe planejar apoio, não para rotular. Cada consulta individual fica na auditoria.
"""

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from apps.academics.models import ClassGroup
from apps.analytics import bi
from apps.analytics.charts import trend_chart
from apps.core.models import create_audit_log
from apps.registry.models import Enrollment

from . import access, ews_validation
from .trajectory import INDICATORS, MIN_POINTS, SOLID_POINTS, TRENDS, class_overview
from .views_projection import _student_or_403


def _behavior(user):
    from apps.pedagogy.access import can_view_occurrences

    return can_view_occurrences(user)


def _validation(school):
    """Resultado aprovado da validação local, para dar a medida de confiança dos indicadores."""
    run = ews_validation.latest_approved(school)
    if run is None:
        return None
    m = run.metrics
    pct = lambda v: v * 100 if v is not None else None
    return {"run": run, "precision2": pct(m.get("pelo_menos_2", {}).get("precisao")), "auc": m.get("auc_contagem"),
            "base": pct(m.get("taxa_base")), "n": m.get("n")}


def _decorate(row, subjects):
    """Rótulo e seta de cada tendência, células alinhadas às disciplinas e percentuais de 0 a 100."""
    for a in [row["overall"], row["attendance"], *row["subjects"].values()]:
        a["label"], a["arrow"] = TRENDS[a["trend"]]
    row["cells"] = [row["subjects"].get(s.pk) for s in subjects]
    rate = row["attendance"]["rate"]
    row["att_pct"] = rate * 100 if rate is not None else None
    return row


def _common(request, school):
    period = bi.resolve_period(request.GET, school)
    return period, {"period": period, "presets": bi.PRESETS, "indicators": INDICATORS, "trends": TRENDS,
                    "min_points": MIN_POINTS, "solid_points": SOLID_POINTS, "validation": _validation(school)}


def class_trajectories(request, class_id):
    user = request.user
    if not access.can_use(user):
        raise PermissionDenied
    cg = get_object_or_404(ClassGroup, pk=class_id, school=user.school)
    allowed = access.class_subjects(user, cg)
    if allowed is not None and not allowed:
        raise PermissionDenied
    period, ctx = _common(request, user.school)
    view = class_overview(cg, period.start, period.end, behavior=_behavior(user), subject_ids=allowed)
    rows = sorted((_decorate(r, view["subjects"]) for r in view["rows"]),
                  key=lambda r: (-len(r["indicators"]), r["student"].full_name))
    create_audit_log(user=user, action="view", request=request, target=cg,
                     detail=f"Consultou trajetórias e indicadores precoces de {cg.name}")
    return render(request, "cognitio/trajectories.html", {
        **ctx, "cg": cg, "rows": rows, "subjects": view["subjects"], "behavior": view["behavior"],
        "only_own_subjects": allowed is not None,
        "flagged": sum(1 for r in rows if r["indicators"]),
    })


def student_trajectory(request, student_id):
    user = request.user
    if not access.can_use(user):
        raise PermissionDenied
    student, subjects = _student_or_403(user, student_id)
    period, ctx = _common(request, user.school)
    enr = Enrollment.objects.filter(student=student, status="ativo").select_related("class_group").first()
    row, view = None, None
    if enr:
        view = class_overview(enr.class_group, period.start, period.end, behavior=_behavior(user),
                              subject_ids=subjects)
        row = next((_decorate(r, view["subjects"]) for r in view["rows"] if r["student"].pk == student.pk), None)
    charts = []
    if row:
        from apps.analytics.services import rules_by_subject

        rules = rules_by_subject(user.school)
        for name, a, ref in [("Todas as disciplinas", row["overall"], None)] + [
                (s["subject"].name, s, _ref(rules.get(pk))) for pk, s in
                sorted(row["subjects"].items(), key=lambda kv: kv[1]["subject"].name)]:
            charts.append({**_shown(a, 10), "name": name, "a": a, "svg": trend_chart(
                a["points"], line=a.get("line"), projection=a.get("projection"), reference=ref,
                mark=a.get("drop_on"))})
        att = row["attendance"]
        charts.append({**_shown(att, 100), "name": "Presença semanal", "a": att, "attendance": True,
                       "svg": trend_chart(att["points"], line=att.get("line"), reference=0.75, mark=att.get("drop_on"),
                                          suffix="%", scale=100)})
    create_audit_log(user=user, action="view", request=request, target=student,
                     detail=f"Consultou a trajetória acadêmica de {student.full_name}")
    return render(request, "cognitio/student_trajectory.html", {
        **ctx, "student": student, "row": row, "charts": charts, "cg": enr.class_group if enr else None,
        "only_own_subjects": subjects is not None,
    })


def _shown(a, scale):
    """Inclinação e projeção na escala da tela (0 a 10 nas notas, pontos percentuais na presença)."""
    p = a.get("projection")
    return {"slope": a["slope30"] * scale if a.get("slope30") is not None else None,
            "proj_low": p["low"] * scale if p else None, "proj_high": p["high"] * scale if p else None}


def _ref(rule):
    passing = float(rule.passing_grade) if rule else 6.0
    return passing / (10.0 if passing <= 10 else 100.0)
