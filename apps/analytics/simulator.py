"""Simulador de cenários: "e se a próxima nota for X?", "e se faltar N dias?".

Tudo aqui é hipotético e nada é gravado. As contas usam as mesmas regras do
painel: a fórmula configurada para a disciplina (``AcademicRule``) via
``services._apply_formula`` e o mesmo critério de frequência de
``bi.attendance_summary`` (presença + atraso contam como presença).

Quando não dá para responder com honestidade, a função devolve ``None`` e a
tela explica o motivo, em vez de inventar um número.
"""

import math
from decimal import ROUND_UP, Decimal, InvalidOperation
from fractions import Fraction

from apps.pedagogy.models import AcademicRule

from .services import _apply_formula

F = AcademicRule.Formula


def parse_number(raw, lo=Decimal("0"), hi=None):
    """Número digitado (aceita vírgula) dentro de [lo, hi], ou None."""
    raw = (raw or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    if not value.is_finite() or value < lo or (hi is not None and value > hi):
        return None
    return value


def simulate_average(values_weights, formula, new_value, new_weight=Decimal("1")):
    """Média da disciplina com uma avaliação hipotética a mais."""
    return _apply_formula(list(values_weights) + [(new_value, new_weight)], formula)


def needed_grade(values_weights, formula, passing, new_weight=Decimal("1")):
    """Menor nota na próxima avaliação que deixa a média >= aprovação.

    Devolve Decimal (0 quando qualquer nota basta) ou None quando a fórmula
    não permite calcular. Quem chama compara com a nota máxima da escala.
    """
    values = [v for v, _ in values_weights if v is not None]
    if formula == F.BEST:
        return Decimal("0") if values and max(values) >= passing else passing
    if formula == F.SUM:
        need = passing - sum(values, Decimal("0"))
    elif formula == F.WEIGHTED:
        weights = sum((w or Decimal("1")) for v, w in values_weights if v is not None)
        acc = sum(v * (w or Decimal("1")) for v, w in values_weights if v is not None)
        if not new_weight:
            return None
        need = (passing * (weights + new_weight) - acc) / new_weight
    else:  # aritmética: o peso não entra na conta
        need = passing * (len(values) + 1) - sum(values, Decimal("0"))
    need = max(need, Decimal("0"))
    # Arredonda para cima na segunda casa: 5,991 precisa de 6,00, não de 5,99.
    return need.quantize(Decimal("0.01"), rounding=ROUND_UP)


def attendance_projection(present_like, total, remaining, future_absences, limit_percent):
    """Frequência ao fim do período se o estudante faltar ``future_absences``
    dos ``remaining`` dias que faltam.

    Hipótese: haverá registro de frequência em cada um desses dias. Devolve
    None se a entrada não fecha (mais faltas que dias, ou nada a contar).
    """
    if remaining is None or future_absences is None or future_absences > remaining:
        return None
    days = total + remaining
    if not days:
        return None
    projected = (present_like + remaining - future_absences) / days * 100
    minimum = 100 - limit_percent if limit_percent is not None else None
    # Maior número de faltas futuras que ainda mantém o mínimo exigido.
    max_absences = None
    if minimum is not None:
        # Fração exata: em ponto flutuante, 30 viraria 29,999... e sairia 29.
        allowed = present_like + remaining - Fraction(str(minimum)) / 100 * days
        max_absences = max(min(math.floor(allowed), remaining), -1)
    return {
        "projected": round(projected, 1),
        "minimum": round(minimum, 1) if minimum is not None else None,
        "below": minimum is not None and projected < minimum,
        "days": days,
        # -1: nem sem nenhuma falta o mínimo é alcançado.
        "max_absences": max_absences,
    }
