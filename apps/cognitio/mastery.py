"""Motor de domínio por habilidade: regras explícitas, auditáveis e configuráveis.

Não é um modelo estatístico treinado: é uma média ponderada das evidências, com
critérios publicados (``MasteryScale``) e a lista das evidências que sustentam
cada conclusão. Escolhas metodológicas (documentadas em
``docs/EIA_COGNITIO_MODELO_DE_EVIDENCIAS.md``):

- evidências recentes pesam mais (meia-vida configurável);
- ausência de resposta não entra na média e não vira dificuldade;
- poucas evidências → "sem evidência suficiente", mesmo com acertos ou erros;
- evidências muito discordantes → "evidência contraditória" (pede nova verificação);
- queda pontual é "oscilação", não "regressão": só uma sequência de quedas vira
  "queda persistente — confirmar".
"""

import math
from collections import Counter, OrderedDict
from dataclasses import dataclass, field

from django.utils import timezone

from apps.core.fmt import dec

STATES = OrderedDict([
    ("nao_avaliado", ("Não avaliada", 1, "Nenhum registro ligado a esta habilidade.")),
    ("insuficiente", ("Sem evidência suficiente", 1, "Há registros, mas poucos para concluir.")),
    ("contraditoria", ("Evidência contraditória", 1, "Resultados muito diferentes entre si: vale uma nova verificação.")),
    ("reverificar", ("Necessita de nova verificação", 1, "O professor pediu nova verificação, com fundamento registrado.")),
    ("dificuldade", ("Dificuldade observada", 2, "Em desenvolvimento inicial nas situações avaliadas.")),
    ("desenvolvimento", ("Em desenvolvimento", 3, "Acertos parciais nas situações avaliadas.")),
    ("consolidacao", ("Em consolidação", 4, "Bons resultados, ainda não estáveis.")),
    ("consolidada", ("Consolidada nas evidências observadas", 5, "Resultados altos e consistentes nas situações avaliadas.")),
])
TRENDS = {
    "evolucao": "Evolução",
    "estavel": "Estável",
    "oscilacao": "Oscilação pontual",
    "queda": "Queda persistente — confirmar com nova evidência",
    "": "Sem dados para tendência",
}
ABBR = {"nao_avaliado": "—", "insuficiente": "?", "contraditoria": "≠", "reverificar": "↻", "dificuldade": "D",
        "desenvolvimento": "E",
        "consolidacao": "C", "consolidada": "✓"}
CSS = {"nao_avaliado": "st-none", "insuficiente": "st-insuf", "contraditoria": "st-contra", "reverificar": "st-contra",
       "dificuldade": "st-1",
       "desenvolvimento": "st-2", "consolidacao": "st-3", "consolidada": "st-4"}


@dataclass
class Assessment:
    state: str
    mean: float | None = None
    n_valid: int = 0
    n_without: int = 0
    weight: float = 0.0
    margin: float | None = None
    uncertainty: str = ""
    trend: str = ""
    last_date: object = None
    stale: bool = False
    sources: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)
    reasons: list = field(default_factory=list)
    judgment: object = None  # decisão do professor aplicada (apply_judgments)
    newer_evidence: bool = False
    computed_state: str = ""

    @property
    def computed_label(self):
        """Estado pelas evidências quando uma decisão do professor está sendo exibida no lugar dele."""
        return STATES[self.computed_state][0] if self.computed_state in STATES else ""

    @property
    def label(self):
        return STATES[self.state][0]

    @property
    def level(self):
        return STATES[self.state][1]

    @property
    def help(self):
        return STATES[self.state][2]

    @property
    def css(self):
        return CSS[self.state]

    @property
    def abbr(self):
        return ABBR[self.state]

    @property
    def trend_label(self):
        return TRENDS.get(self.trend, "")

    @property
    def percent(self):
        return None if self.mean is None else round(self.mean * 100)


_SOURCE_LABELS = {}


def _source_label(code):
    """Nome da origem sem ``get_source_type_display()``, que custava 2,8 s num painel com 19 mil evidências."""
    if not _SOURCE_LABELS:
        from .models import SkillEvidence

        _SOURCE_LABELS.update(SkillEvidence.Source.choices)
    return _SOURCE_LABELS.get(code, code)


def assess(evidences, scale, today=None, explain=True):
    """Classifica a habilidade a partir das evidências (lista de ``SkillEvidence``).

    ``explain=False`` devolve o mesmo estado sem montar as frases de explicação nem a contagem por
    origem: para gráficos que só usam o estado (evolução por período), onde a avaliação se repete
    para cada ponto."""
    today = today or timezone.localdate()
    evs = sorted(evidences, key=lambda e: (e.observed_on, e.pk or 0))
    if not evs:
        return Assessment("nao_avaliado")
    valid = [e for e in evs if e.ratio is not None and e.weight > 0]
    without = [e for e in evs if e.ratio is None]
    a = Assessment("insuficiente", n_valid=len(valid), n_without=len(without), evidence=evs,
                   sources=dict(Counter(_source_label(e.source_type) for e in evs)) if explain else {},
                   last_date=evs[-1].observed_on)
    if without and explain:
        a.reasons.append(f"{len(without)} registro(s) sem resposta, ausência ou não entrega: não contam como "
                         "dificuldade.")
    if not valid:
        if explain:
            a.reasons.append("Nenhuma evidência de desempenho ainda.")
        return a
    half = float(scale.half_life_days or 120)
    ws = [e.weight * 0.5 ** (max((today - e.observed_on).days, 0) / half) for e in valid]
    total = sum(ws)
    mean = sum(w * e.ratio for w, e in zip(ws, valid)) / total if total else None
    a.mean = mean
    a.weight = round(sum(e.weight for e in valid), 2)
    a.last_date = valid[-1].observed_on
    a.stale = (today - a.last_date).days > scale.stale_days
    var = sum(w * (e.ratio - mean) ** 2 for w, e in zip(ws, valid)) / total if total else 0
    sd = math.sqrt(var)
    n_eff = total ** 2 / sum(w * w for w in ws) if total else 0
    a.margin = round(sd / math.sqrt(n_eff), 3) if n_eff > 1 else None
    if n_eff < 3 or (a.margin is not None and a.margin > 0.15):
        a.uncertainty = "alta"
    elif a.margin is not None and a.margin > 0.08:
        a.uncertainty = "média"
    else:
        a.uncertainty = "baixa"
    if len(valid) >= 3:
        mid = len(valid) // 2
        first = sum(e.ratio for e in valid[:mid]) / mid
        second = sum(e.ratio for e in valid[mid:]) / (len(valid) - mid)
        diff = second - first
        if diff >= 0.15:
            a.trend = "evolucao"
        elif diff <= -0.15:
            earlier = sum(e.ratio for e in valid[:-2]) / max(len(valid) - 2, 1)
            a.trend = "queda" if all(e.ratio < earlier - 0.2 for e in valid[-2:]) else "oscilacao"
        else:
            a.trend = "estavel"
    t1, t2, t3 = float(scale.t1), float(scale.t2), float(scale.t3)
    if explain:
        a.reasons.append(f"Média ponderada {dec(mean)} em {len(valid)} evidência(s) válida(s) de "
                         f"{len({e.source_type for e in valid})} tipo(s); peso total {dec(a.weight, 1)}.")
    if len(valid) < scale.min_evidence or a.weight < float(scale.min_weight):
        if explain:
            a.reasons.append(f"Critério: são precisas ao menos {scale.min_evidence} evidências e peso "
                             f"{dec(scale.min_weight, 1)} para concluir.")
        return a
    ratios = [e.ratio for e in valid]
    if max(ratios) - min(ratios) >= 0.5 and sd >= 0.25:
        a.state = "contraditoria"
        if explain:
            a.reasons.append("Há resultados muito altos e muito baixos: a situação de avaliação pode ter influído.")
        return a
    if mean < t1:
        a.state = "dificuldade"
    elif mean < t2:
        a.state = "desenvolvimento"
    elif mean < t3:
        a.state = "consolidacao"
    else:
        a.state = "consolidada"
    if explain:
        a.reasons.append(f"Cortes da escola: dificuldade < {dec(t1)}; em desenvolvimento < {dec(t2)}; "
                         f"em consolidação < {dec(t3)}; consolidada a partir de {dec(t3)}.")
    return a


def sort_key(e):
    return (e.observed_on, e.pk or 0)


def state_only(evs, scale, today):
    """Só o estado que ``assess(evs, scale, today)`` daria, sem montar a avaliação completa.

    Para a evolução por período, que repete a classificação de cada par para cada fim de período (87 mil
    vezes numa escola de 600 estudantes). ``evs`` precisa vir ordenada por ``sort_key``, como ``assess``
    ordena: a soma em ponto flutuante depende da ordem, e um estado na fronteira de um corte poderia mudar.
    A equivalência com ``assess`` é conferida em ``tests/test_state_only.py``."""
    if not evs:
        return "nao_avaliado"
    valid = [e for e in evs if e.ratio is not None and e.weight > 0]
    if not valid:
        return "insuficiente"
    if len(valid) < scale.min_evidence or round(sum(e.weight for e in valid), 2) < float(scale.min_weight):
        return "insuficiente"
    half = float(scale.half_life_days or 120)
    ws = [e.weight * 0.5 ** (max((today - e.observed_on).days, 0) / half) for e in valid]
    total = sum(ws)
    mean = sum(w * e.ratio for w, e in zip(ws, valid)) / total if total else None
    var = sum(w * (e.ratio - mean) ** 2 for w, e in zip(ws, valid)) / total if total else 0
    ratios = [e.ratio for e in valid]
    if max(ratios) - min(ratios) >= 0.5 and math.sqrt(var) >= 0.25:
        return "contraditoria"
    if mean < float(scale.t1):
        return "dificuldade"
    if mean < float(scale.t2):
        return "desenvolvimento"
    if mean < float(scale.t3):
        return "consolidacao"
    return "consolidada"


def with_items(evs):
    """Liga cada evidência à sua habilidade com uma consulta para as habilidades distintas.

    Substitui ``select_related("item")``, que montava um objeto de habilidade por evidência (19 mil
    objetos para algumas centenas de habilidades numa escola grande)."""
    from apps.curriculum.models import CurriculumItem

    from .models import SkillEvidence

    items = CurriculumItem.objects.in_bulk({e.item_id for e in evs})
    field = SkillEvidence._meta.get_field("item")
    for e in evs:
        field.set_cached_value(e, items[e.item_id])
    return evs


def group_evidence(qs):
    """{(student_id, item_id): [evidências]}"""
    out = {}
    for e in qs:
        out.setdefault((e.student_id, e.item_id), []).append(e)
    return out


def trajectory(evidences, scale, cutoffs):
    """Estado acumulado da habilidade ao fim de cada período (``cutoffs``: [(rótulo, data)])."""
    out = []
    for label, end in cutoffs:
        upto = [e for e in evidences if e.observed_on <= end]
        out.append((label, assess(upto, scale, today=end)))
    return out


def apply_judgments(assessments):
    """Aplica as decisões ativas dos professores (``SkillJudgment``) a {(estudante, habilidade): Assessment}.

    Sem evidência mais nova que a decisão, o estado exibido passa a ser o decidido (``a.computed_state``
    guarda o calculado) e o fundamento entra nas razões. Com evidência mais nova, o estado calculado vale e
    ``a.newer_evidence`` pede revisão. Uma consulta para o conjunto todo.
    """
    from .models import SkillJudgment

    if not assessments:
        return assessments
    keys = list(assessments)
    found = SkillJudgment.objects.filter(student_id__in={k[0] for k in keys}, item_id__in={k[1] for k in keys},
                                         active=True).order_by("decided_on", "pk")
    by_key = {(j.student_id, j.item_id): j for j in found}
    for key, a in assessments.items():
        j = by_key.get(key)
        if j is None:
            continue
        a.judgment = j
        a.newer_evidence = bool(a.last_date and a.last_date > j.decided_on)
        if not a.newer_evidence:
            a.computed_state = a.state
            a.state = j.state
            a.reasons = [f"Decisão do professor em {j.decided_on:%d/%m/%Y}: {j.rationale}"] + list(a.reasons)
    return assessments
