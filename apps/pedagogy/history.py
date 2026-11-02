"""Histórico de alterações das atividades de casa e dos trabalhos em grupo
(ver ``ActivityChange`` e ``GroupWorkChange``).

O retrato é tirado ANTES de o formulário validar: o ModelForm escreve os
valores novos na instância durante ``is_valid()``, e um retrato tirado depois
já sairia igual ao novo.
"""
from datetime import date

from .models import Activity, ActivityChange, GroupWork, GroupWorkChange

# (campo, rótulo, a família vê?)
TRACKED = (
    ("title", "Título", True),
    ("subject", "Disciplina", True),
    ("work_mode", "Realização", True),
    ("content", "Conteúdo", True),
    ("objective", "Objetivo", True),
    ("description", "Instruções", True),
    ("materials", "Materiais necessários", True),
    ("criteria", "Critérios de avaliação", True),
    ("published_date", "Data de publicação", True),
    ("deadline", "Data de entrega", True),
    ("class_date", "Data de aplicação", True),
    ("internal_notes", "Observações internas", False),
)

# Trabalho em grupo: tudo o que está no formulário aparece à família.
WORK_TRACKED = (
    ("title", "Título", True),
    ("subject", "Disciplina", True),
    ("description", "O que deve ser feito", True),
    ("objectives", "Objetivos", True),
    ("guidelines", "Orientações e critérios", True),
    ("materials", "Materiais necessários", True),
    ("presentation", "Forma de apresentação", True),
    ("notes", "Observações complementares", True),
    ("published_date", "Data de publicação", True),
    ("deadline", "Prazo de entrega", True),
    ("delivery_mode", "Modalidade de entrega", True),
)


def _tracked(obj):
    return WORK_TRACKED if isinstance(obj, GroupWork) else TRACKED


def _display(obj, name):
    value = getattr(obj, name)
    if value is None or value == "":
        return ""
    if obj._meta.get_field(name).choices:
        return getattr(obj, f"get_{name}_display")()
    if isinstance(value, date):
        return f"{value:%d/%m/%Y}"
    return str(value)


def snapshot(obj):
    return {name: _display(obj, name) for name, _, _ in _tracked(obj)}


def diff(obj, before):
    """Campos que mudaram desde ``before`` (um ``snapshot``)."""
    out = []
    for name, label, family in _tracked(obj):
        after = _display(obj, name)
        if before.get(name, "") != after:
            out.append({"label": label, "before": before.get(name, ""), "after": after,
                        "family": family})
    return out


def attachment_entries(added=(), removed=()):
    return [
        {"label": "Anexo incluído", "before": "", "after": n, "family": True} for n in added
    ] + [
        {"label": "Anexo removido", "before": n, "after": "", "family": True} for n in removed
    ]


def record(obj, user, family_saw, fields):
    """Grava a alteração se houver o que gravar. Rascunho não tem histórico."""
    if not fields or obj.status == obj.Status.DRAFT:
        return None
    if isinstance(obj, Activity):
        return ActivityChange.objects.create(activity=obj, changed_by=user, family_saw=family_saw, fields=fields)
    return GroupWorkChange.objects.create(group_work=obj, changed_by=user, family_saw=family_saw, fields=fields)


def summary(fields, family_only=False):
    """"Instruções, data de entrega" — para a auditoria e as telas."""
    labels = [f["label"] for f in fields if f.get("family") or not family_only]
    return ", ".join(dict.fromkeys(labels)).lower()
