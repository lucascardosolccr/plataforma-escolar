"""Resumo por componente do mapa de um estudante, para o painel do estudante (BI).

Mesmas regras de acesso do mapa individual (``access.student_subjects``): professor só nas
disciplinas que leciona ao estudante, coordenação no seu escopo, direção sem restrição de
disciplina; família, estudante, secretaria e administração não recebem nada (``None``).
São só contagens de estados; o detalhe e as evidências ficam no mapa do EIA-Cognitio.
"""

from collections import Counter, OrderedDict, defaultdict

from . import access
from .mastery import CSS, STATES, apply_judgments, assess
from .models import MasteryScale, SkillEvidence

ORDER = ["consolidada", "consolidacao", "desenvolvimento", "dificuldade", "contraditoria", "reverificar",
         "insuficiente"]


def student_components(user, student, start=None, end=None):
    """[{component, total, counts: [(estado, rótulo, css, n)]}] ou None sem acesso."""
    subjects = access.student_subjects(user, student)
    if subjects is not None and not subjects:
        return None
    evs = SkillEvidence.objects.filter(student=student).select_related("item")
    if subjects is not None:
        evs = evs.filter(subject_id__in=subjects)
    if start:
        evs = evs.filter(observed_on__gte=start)
    if end:
        evs = evs.filter(observed_on__lte=end)
    by_item = defaultdict(list)
    for e in evs:
        by_item[e.item_id].append(e)
    scale = MasteryScale.for_school(student.school)
    comps = OrderedDict()
    assessed = apply_judgments({(student.pk, iid): assess(evs_, scale) for iid, evs_ in by_item.items()})
    for iid, item_evs in by_item.items():
        comp = item_evs[0].item.component or "Outros"
        comps.setdefault(comp, Counter())[assessed[(student.pk, iid)].state] += 1
    return [{"component": comp, "total": sum(c.values()),
             "counts": [(s, STATES[s][0], CSS[s], c[s]) for s in ORDER if c[s]]}
            for comp, c in sorted(comps.items())]
