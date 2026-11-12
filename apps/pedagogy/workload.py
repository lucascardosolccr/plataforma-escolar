"""Concentração de prazos: dias em que a turma tem entregas e provas demais ao mesmo tempo.

Fundamento: espaçar as entregas ensina mais e sobrecarrega menos do que amontoá-las na mesma data (prática
distribuída — Cepeda et al., 2006; Rohrer, Dedrick & Stershic, 2015, as mesmas fontes de ``study/spacing.py``).
Quando prova, trabalho e atividade caem no mesmo dia, o estudante divide a atenção e estuda pior. Esta tela só
mostra o que já está marcado, para a equipe reequilibrar — nenhuma data é alterada automaticamente.

Carga do dia = soma de pesos: prova e trabalho pesam 2 (preparo longo), atividade pesa 1. A partir de
``HEAVY`` o dia é sinalizado. É heurística de planejamento, não regra: cabe ao professor decidir.
"""

from collections import defaultdict

from .models import Activity, Evaluation, GroupWork

WEIGHTS = {"prova": 2, "trabalho": 2, "atividade": 1}
HEAVY = 4
KIND_LABEL = {"prova": "Prova", "trabalho": "Trabalho em grupo", "atividade": "Atividade"}


def deliverables(class_group, start, end):
    """[(data, tipo, objeto)] de tudo que 'vence' para a turma no período (só itens publicados)."""
    rows = []
    for a in (Activity.objects.filter(class_group=class_group, status=Activity.Status.PUBLISHED,
                                      deadline__gte=start, deadline__lte=end).select_related("subject")):
        rows.append((a.deadline, "atividade", a))
    for g in (GroupWork.objects.filter(class_group=class_group, status=GroupWork.Status.PUBLISHED,
                                       deadline__gte=start, deadline__lte=end).select_related("subject")):
        rows.append((g.deadline, "trabalho", g))
    for e in (Evaluation.objects.filter(class_group=class_group, status=Evaluation.Status.PUBLISHED,
                                        date__gte=start, date__lte=end).select_related("subject")):
        rows.append((e.date, "prova", e))
    return rows


def by_day(class_group, start, end, heavy=HEAVY):
    """Por dia com algum prazo: itens, carga somada e se o dia está sobrecarregado."""
    days = defaultdict(list)
    for when, kind, obj in deliverables(class_group, start, end):
        days[when].append({"kind": kind, "label": KIND_LABEL[kind], "title": obj.title,
                           "subject": getattr(obj, "subject", None)})
    out = []
    for when in sorted(days):
        items = sorted(days[when], key=lambda i: -WEIGHTS[i["kind"]])
        load = sum(WEIGHTS[i["kind"]] for i in items)
        out.append({"date": when, "items": items, "count": len(items), "load": load,
                    "overloaded": load >= heavy})
    return out


def overloaded_days(class_group, start, end, heavy=HEAVY):
    """Só os dias sobrecarregados do período."""
    return [d for d in by_day(class_group, start, end, heavy) if d["overloaded"]]
