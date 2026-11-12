"""Concordância entre professores que observam a MESMA habilidade do MESMO estudante.

Pergunta: quando dois professores olham para a mesma habilidade do mesmo estudante, na mesma época, eles
registram o mesmo nível? Concordância baixa não é erro de ninguém — é sinal de que a rubrica precisa de
calibração e o olhar avaliativo, de alinhamento. É instrumento de coordenação, não avaliação de professor.

Método (``core.stats``, Python puro, sem dependência nova):

- **Ocasião:** observações do mesmo ``(estudante, habilidade)`` cujas datas cabem numa janela de
  ``WINDOW_DAYS`` dias. Sem a janela, comparar observações distantes mediria *crescimento*, não concordância.
- **Pares:** em cada ocasião, todo par de observações de professores DIFERENTES (o mesmo professor
  observando duas vezes não é concordância entre avaliadores). O nível é ordinal, de 1 a 5.
- **Coeficientes:** concordância bruta (exata e dentro de 1 nível), **kappa ponderado quadrático** (Cohen,
  1968) e **AC2 de Gwet** (2008). O AC2 acompanha o kappa porque, quando quase tudo cai num nível só, o
  kappa despenca mesmo com concordância alta (paradoxo do kappa); o AC2 é robusto a isso.
- **Mínimo:** ``MIN_PAIRS`` pares, senão "dados insuficientes" — poucos pares dão coeficiente instável.
- É descritivo (mede concordância); não há teste de hipótese nem correção de múltiplas comparações.
"""

from collections import defaultdict
from datetime import timedelta
from itertools import combinations

from apps.core import stats

from .models import SkillObservation

WINDOW_DAYS = 15   # observações além disto medem crescimento, não concordância
MIN_PAIRS = 12     # abaixo disto, o coeficiente é instável demais para mostrar
LEVELS = [level.value for level in SkillObservation.Level]
DISCORDANT = 2     # diferença de 2+ níveis num par: pauta de calibração


def _occasions(obs, window):
    """Agrupa observações (ordenadas por data) em ocasiões cujo intervalo cabe em ``window`` dias."""
    groups, start = [], None
    for o in obs:
        if start is None or (o.observed_on - start) > timedelta(days=window):
            groups.append([])
            start = o.observed_on
        groups[-1].append(o)
    return groups


def _pairs_of(occasion):
    """Pares (obs_a, obs_b) de professores diferentes dentro de uma ocasião."""
    return [(a, b) for a, b in combinations(occasion, 2) if a.teacher_id != b.teacher_id]


def summary(school, start, end, *, class_group=None, class_ids=None, subject=None, student_ids=None,
            window=WINDOW_DAYS, min_pairs=MIN_PAIRS):
    """Concordância entre observadores no período, com recorte opcional de turma, disciplina e escopo.

    Devolve ``{"enough", "pairs", "occasions", "observations", "percent", "kappa", "ac2", "labels",
    "by_skill", "discordant"}``. ``enough`` é False quando há menos de ``min_pairs`` pares.
    """
    qs = (SkillObservation.objects.filter(school=school, observed_on__gte=start, observed_on__lte=end,
                                          teacher__isnull=False)
          .select_related("student", "item", "subject", "teacher"))
    if class_group is not None:
        qs = qs.filter(class_group=class_group)
    if class_ids is not None:
        qs = qs.filter(class_group_id__in=class_ids)
    if subject is not None:
        qs = qs.filter(subject=subject)
    if student_ids is not None:
        qs = qs.filter(student_id__in=student_ids)

    by_key = defaultdict(list)
    n_obs = 0
    for o in qs.order_by("student_id", "item_id", "observed_on"):
        by_key[(o.student_id, o.item_id)].append(o)
        n_obs += 1

    pairs, by_skill_pairs, skill_item, occasions, discordant = [], defaultdict(list), {}, 0, []
    for (sid, iid), obs in by_key.items():
        for occ in _occasions(obs, window):
            occ_pairs = _pairs_of(occ)
            if not occ_pairs:
                continue
            occasions += 1
            skill_item[iid] = occ[0].item
            for a, b in occ_pairs:
                pairs.append((a.level, b.level))
                by_skill_pairs[iid].append((a.level, b.level))
            worst = max(abs(a.level - b.level) for a, b in occ_pairs)
            if worst >= DISCORDANT:
                ref = occ[0]
                discordant.append({
                    "student": ref.student, "item": ref.item, "subject": ref.subject, "gap": worst,
                    "on": ref.observed_on,
                    "ratings": sorted(({"teacher": o.teacher, "level": o.level,
                                        "label": o.get_level_display()} for o in occ),
                                      key=lambda r: r["level"]),
                })

    n_pairs = len(pairs)
    if n_pairs < min_pairs:
        return {"enough": False, "pairs": n_pairs, "occasions": occasions, "observations": n_obs,
                "min_pairs": min_pairs, "window": window}

    kappa = stats.weighted_kappa(pairs, LEVELS)
    ac2 = stats.gwet_ac2(pairs, LEVELS)
    by_skill = []
    for iid, pr in by_skill_pairs.items():
        pct = stats.percent_agreement(pr)
        by_skill.append({
            "item": skill_item[iid],
            "pairs": len(pr), "percent": pct,
            "kappa": stats.weighted_kappa(pr, LEVELS) if len(pr) >= min_pairs else None,
        })
    by_skill.sort(key=lambda r: (r["percent"]["within1"], r["percent"]["exact"]))
    discordant.sort(key=lambda d: (-d["gap"], d["on"]))
    return {
        "enough": True, "pairs": n_pairs, "occasions": occasions, "observations": n_obs,
        "min_pairs": min_pairs, "window": window,
        "percent": stats.percent_agreement(pairs),
        "kappa": kappa, "ac2": ac2,
        "labels": {"kappa": stats.agreement_label(kappa), "ac2": stats.agreement_label(ac2)},
        "by_skill": by_skill, "discordant": discordant,
    }
