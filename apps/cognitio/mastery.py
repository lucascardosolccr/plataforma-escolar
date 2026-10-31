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

STATES = OrderedDict([
    ("nao_avaliado", ("Não avaliada", 1, "Nenhum registro ligado a esta habilidade.")),
    ("insuficiente", ("Sem evidência suficiente", 1, "Há registros, mas poucos para concluir.")),
    ("contraditoria", ("Evidência contraditória", 1, "Resultados muito diferentes entre si: vale uma nova verificação.")),
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
ABBR = {"nao_avaliado": "—", "insuficiente": "?", "contraditoria": "≠", "dificuldade": "D", "desenvolvimento": "E",
        "consolidacao": "C", "consolidada": "✓"}
CSS = {"nao_avaliado": "m-none", "insuficiente": "m-insuf", "contraditoria": "m-contra", "dificuldade": "m-1",
       "desenvolvimento": "m-2", "consolidacao": "m-3", "consolidada": "m-4"}


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


def assess(evidences, scale, today=None):
    """Classifica a habilidade a partir das evidências (lista de ``SkillEvidence``)."""
    today = today or timezone.localdate()
    evs = sorted(evidences, key=lambda e: (e.observed_on, e.pk or 0))
    if not evs:
        return Assessment("nao_avaliado")
    valid = [e for e in evs if e.ratio is not None and e.weight > 0]
    without = [e for e in evs if e.ratio is None]
    a = Assessment("insuficiente", n_valid=len(valid), n_without=len(without), evidence=evs,
                   sources=dict(Counter(e.get_source_type_display() for e in evs)),
                   last_date=evs[-1].observed_on)
    if without:
        a.reasons.append(f"{len(without)} registro(s) sem resposta, ausência ou não entrega: não contam como "
                         "dificuldade.")
    if not valid:
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
    a.reasons.append(f"Média ponderada {mean:.2f} em {len(valid)} evidência(s) válida(s) de "
                     f"{len({e.source_type for e in valid})} tipo(s); peso total {a.weight:.1f}.")
    if len(valid) < scale.min_evidence or a.weight < float(scale.min_weight):
        a.reasons.append(f"Critério: são precisas ao menos {scale.min_evidence} evidências e peso "
                         f"{float(scale.min_weight):.1f} para concluir.")
        return a
    ratios = [e.ratio for e in valid]
    if max(ratios) - min(ratios) >= 0.5 and sd >= 0.25:
        a.state = "contraditoria"
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
    a.reasons.append(f"Cortes da escola: dificuldade < {t1:.2f}; em desenvolvimento < {t2:.2f}; "
                     f"em consolidação < {t3:.2f}; consolidada a partir de {t3:.2f}.")
    return a


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
