"""Etapa escolar, idade de referência e distorção idade-série.

- **Etapa:** 1 a 9 para o 1º ao 9º ano do ensino fundamental e 10 a 12 para a 1ª à 3ª série do ensino médio,
  lida do texto da série ou do nome da turma ("6º Ano B", "1ª série do EM").
- **Idade de referência:** ingresso no 1º ano aos 6 anos completos até 31 de março do ano letivo (Resolução
  CNE/CEB nº 2, de 9 de outubro de 2018). Logo, a idade esperada em 31/03 é etapa + 5.
- **Distorção idade-série:** idade 2 anos ou mais acima da esperada, a mesma definição da taxa de distorção
  idade-série do INEP (Indicadores Educacionais do Censo Escolar). Assim o número da escola é comparável ao
  da rede e do país.
"""

import datetime
import re

from apps.curriculum.models import _ALIASES, _plain

DISTORTION_YEARS = 2


def parse_stage(text):
    """Etapa (1–12) a partir de "3º ano", "3o Ano A", "1ª série EM"…, ou None."""
    t = _plain(text or "")
    if not t:
        return None
    m = re.search(r"(\d{1,2})\s*[ºªo°a]?\s*(ano|serie)", t)
    if not m:
        return None
    n, kind = int(m.group(1)), m.group(2)
    high_school = "medio" in t or re.search(r"\bem\b", t) is not None
    if high_school or (kind == "serie" and "fundamental" not in t and re.search(r"\bef\b", t) is None):
        return 9 + n if 1 <= n <= 3 else None
    return n if 1 <= n <= 9 else None


def stage_of_class(class_group):
    return parse_stage(class_group.grade) or parse_stage(class_group.name)


def stage_label(stage):
    if not stage:
        return ""
    return f"{stage}º ano" if stage <= 9 else f"{stage - 9}ª série do médio"


def age_on_cutoff(birth_date, year):
    """Idade completa em 31 de março do ano letivo."""
    if not birth_date:
        return None
    cutoff = datetime.date(year, 3, 31)
    return year - birth_date.year - ((cutoff.month, cutoff.day) < (birth_date.month, birth_date.day))


def expected_age(stage):
    return stage + 5 if stage else None


def distortion(birth_date, year, stage):
    """Anos acima da idade esperada (0 se não há atraso), ou None sem data de nascimento ou etapa."""
    age, exp = age_on_cutoff(birth_date, year), expected_age(stage)
    if age is None or exp is None:
        return None
    return max(age - exp, 0)


def subject_key(name):
    """Nome comum de um componente em anos e escolas diferentes ("Português" e "Língua Portuguesa")."""
    plain = _plain(name or "")
    if plain in _ALIASES:
        return _ALIASES[plain]
    for alias, comp in _ALIASES.items():
        if plain.startswith(alias):
            return comp
    return (name or "").strip()
