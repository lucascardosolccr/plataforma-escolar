"""Importação dos anos anteriores por planilha (.xlsx ou .csv), em duas etapas: conferir e confirmar.

Uma linha por estudante e ano. Colunas reconhecidas (a ordem não importa, acentos e maiúsculas também não):

- ``codigo`` (código do aluno na escola) ou ``estudante`` (nome completo); ``nascimento`` desfaz homônimos;
- ``ano``, ``serie`` e ``escola`` (obrigatórias);
- ``resultado``, ``frequencia`` (%), ``media_aprovacao``, ``escala`` (nota máxima, 10 se em branco) e
  ``observacao`` (opcionais);
- **qualquer outra coluna é um componente** (Matemática, Português...), com a nota final ou o conceito.

Linha repetida (mesmo estudante, ano e escola) atualiza o registro e troca as notas: reenviar a planilha
corrigida não duplica nada.
"""

import re
from decimal import Decimal, InvalidOperation

from django.core import signing
from django.db import transaction

from apps.registry.importer import (MAX_FILE_BYTES, MAX_ROWS, ImportFileError, _norm, _read_csv, _read_xlsx,
                                    parse_date)
from apps.registry.models import Student

from .models import Outcome, PriorGrade, PriorYear
from .stages import parse_stage

FIXED = {
    "codigo": "codigo", "ra": "codigo", "codigo do aluno": "codigo", "codigo do estudante": "codigo",
    "estudante": "estudante", "aluno": "estudante", "nome": "estudante", "nome do estudante": "estudante",
    "nome do aluno": "estudante", "nascimento": "nascimento", "data de nascimento": "nascimento",
    "ano": "ano", "ano letivo": "ano", "serie": "serie", "ano serie": "serie", "etapa": "serie",
    "escola": "escola", "escola de origem": "escola", "resultado": "resultado", "resultado final": "resultado",
    "situacao": "resultado", "frequencia": "frequencia", "frequencia anual": "frequencia",
    "media aprovacao": "media_aprovacao", "media de aprovacao": "media_aprovacao", "escala": "escala",
    "nota maxima": "escala", "observacao": "observacao", "obs": "observacao",
}
REQUIRED = ("ano", "serie", "escola")

OUTCOMES = [
    (r"conselho", Outcome.COUNCIL),
    (r"depend|progress", Outcome.PARTIAL),
    (r"(reprov|retid).*(falta|frequ)", Outcome.RETAINED_ABSENCE),
    (r"reprov|retid", Outcome.RETAINED),
    (r"transf", Outcome.TRANSFERRED),
    (r"abandon|evad|desist", Outcome.DROPOUT),
    (r"aprov|promov", Outcome.APPROVED),
]

TEMPLATE_HEADERS = ["codigo", "estudante", "nascimento", "ano", "serie", "escola", "resultado", "frequencia",
                    "Língua Portuguesa", "Matemática", "Ciências", "História", "Geografia", "Arte",
                    "Educação Física", "Língua Inglesa"]


def parse_outcome(text):
    t = _norm(text)
    if not t:
        return Outcome.UNKNOWN
    for pattern, outcome in OUTCOMES:
        if re.search(pattern, t):
            return outcome
    return None


def parse_number(text):
    t = str(text or "").strip().replace("%", "").replace(" ", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        value = Decimal(t)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def read_matrix(uploaded):
    name = (uploaded.name or "").lower()
    if uploaded.size > MAX_FILE_BYTES:
        raise ImportFileError("O arquivo passa de 5 MB. Divida a planilha em partes menores.")
    data = uploaded.read()
    if name.endswith(".xlsx"):
        matrix = _read_xlsx(data)
    elif name.endswith(".csv"):
        matrix = _read_csv(data)
    else:
        raise ImportFileError("Envie uma planilha .xlsx (Excel) ou .csv.")
    matrix = [[str(v if v is not None else "").strip() for v in row] for row in matrix
              if any(str(v or "").strip() for v in row)]
    if not matrix:
        raise ImportFileError("A planilha está vazia.")
    if len(matrix) > MAX_ROWS + 1:
        raise ImportFileError(f"A planilha tem {len(matrix) - 1} linhas; o limite por envio é {MAX_ROWS}.")
    return matrix


def seal(matrix):
    return signing.dumps(matrix, salt="longitudinal.import", compress=True)


def unseal(token):
    try:
        return signing.loads(token, salt="longitudinal.import", max_age=6 * 3600)
    except signing.BadSignature:
        raise ImportFileError("A conferência expirou ou foi alterada. Envie a planilha de novo.") from None


def _student_index(school):
    by_code, by_name = {}, {}
    for s in Student.objects.filter(school=school).only("pk", "first_name", "last_name", "code", "birth_date"):
        if s.code:
            by_code[_norm(s.code)] = s
        by_name.setdefault(_norm(s.full_name), []).append(s)
    return by_code, by_name


def validate(school, matrix):
    """(linhas conferidas, avisos). Cada linha: {"n", "student", "data", "grades", "errors", "warnings"}."""
    headers = matrix[0]
    keys, subjects, warnings = [], {}, []
    for i, h in enumerate(headers):
        key = FIXED.get(_norm(h))
        if key and key not in keys:
            keys.append(key)
        elif h.strip():
            keys.append(None)
            subjects[i] = h.strip()[:80]
        else:
            keys.append(None)
    missing = [k for k in REQUIRED if k not in keys]
    if "codigo" not in keys and "estudante" not in keys:
        missing.append("codigo ou estudante")
    if missing:
        raise ImportFileError("Faltam colunas: " + ", ".join(missing) + ". Baixe o modelo para ver os cabeçalhos.")
    if not subjects:
        warnings.append("Nenhuma coluna de componente (notas) foi encontrada: só série, resultado e frequência "
                        "serão importados.")
    by_code, by_name = _student_index(school)
    out, seen = [], set()
    for n, values in enumerate(matrix[1:], start=2):
        cell = {k: (values[i] if i < len(values) else "") for i, k in enumerate(keys) if k}
        errors, notes = [], []
        student = None
        code, name = cell.get("codigo", ""), cell.get("estudante", "")
        if code:
            student = by_code.get(_norm(code))
            if student is None:
                errors.append(f"Código “{code}” não encontrado nesta escola.")
        elif name:
            found = by_name.get(_norm(name), [])
            birth = parse_date(cell.get("nascimento", ""))
            if birth:
                found = [s for s in found if s.birth_date == birth]
            if len(found) == 1:
                student = found[0]
            elif not found:
                errors.append(f"Estudante “{name}” não encontrado (confira o nome completo ou use o código).")
            else:
                errors.append(f"Há {len(found)} estudantes chamados “{name}”: informe o código ou o nascimento.")
        else:
            errors.append("Sem código nem nome do estudante.")
        year = parse_number(cell.get("ano"))
        year = int(year) if year is not None and year == int(year) and 1980 <= year <= 2100 else None
        if year is None:
            errors.append("Ano inválido.")
        serie = cell.get("serie", "")[:40]
        if not serie:
            errors.append("Série em branco.")
        stage = parse_stage(serie)
        if serie and stage is None:
            notes.append(f"Série “{serie}” não reconhecida como etapa: idade-série não será calculada.")
        school_name = cell.get("escola", "")[:150]
        if not school_name:
            errors.append("Escola em branco.")
        outcome = parse_outcome(cell.get("resultado", ""))
        if outcome is None:
            errors.append(f"Resultado “{cell.get('resultado')}” não reconhecido.")
        freq = parse_number(cell.get("frequencia"))
        if cell.get("frequencia") and (freq is None or not 0 <= freq <= 100):
            errors.append("Frequência deve estar entre 0 e 100.")
        scale = parse_number(cell.get("escala")) or Decimal("10")
        if scale <= 0 or scale > 1000:
            errors.append("Escala inválida.")
            scale = Decimal("10")
        passing = parse_number(cell.get("media_aprovacao"))
        if passing is not None:
            passing = passing * 10 / scale
            if not 0 <= passing <= 10:
                errors.append("Média de aprovação fora da escala.")
                passing = None
        grades = []
        for i, subject in subjects.items():
            raw = values[i] if i < len(values) else ""
            if not raw:
                continue
            value = parse_number(raw)
            if value is None:
                grades.append({"subject": subject, "value": None, "concept": raw[:12]})
            elif not 0 <= value <= scale:
                errors.append(f"{subject}: nota {raw} fora da escala de 0 a {scale.normalize()}.")
            else:
                grades.append({"subject": subject, "value": str(value), "concept": ""})
        key = (student.pk if student else None, year, _norm(school_name))
        if student and key in seen:
            errors.append("Linha repetida na planilha (mesmo estudante, ano e escola).")
        seen.add(key)
        out.append({
            "n": n, "student": student, "errors": errors, "warnings": notes, "grades": grades,
            "data": {"year": year,
                     "grade_label": serie, "stage": stage, "school_name": school_name,
                     "outcome": outcome or Outcome.UNKNOWN, "attendance_percent": freq, "passing_grade": passing,
                     "scale": scale, "notes": cell.get("observacao", "")[:300]},
        })
    return out, warnings


@transaction.atomic
def apply(school, rows, user):
    created = updated = 0
    for r in rows:
        if r["errors"]:
            continue
        d = r["data"]
        obj, was_created = PriorYear.objects.update_or_create(
            student=r["student"], year=d["year"], school_name=d["school_name"],
            defaults={"school": school, "grade_label": d["grade_label"], "stage": d["stage"],
                      "outcome": d["outcome"], "attendance_percent": d["attendance_percent"],
                      "passing_grade": d["passing_grade"], "notes": d["notes"],
                      "source": PriorYear.Source.IMPORT, "created_by": user})
        obj.grades.all().delete()
        PriorGrade.objects.bulk_create([
            PriorGrade(record=obj, subject=g["subject"], value=Decimal(g["value"]) if g["value"] else None,
                       scale_max=d["scale"], concept=g["concept"]) for g in r["grades"]])
        created += was_created
        updated += not was_created
    return created, updated
