"""Histórico de alterações das atividades de casa (ver ``ActivityChange``).

O retrato é tirado ANTES de o formulário validar: o ModelForm escreve os
valores novos na instância durante ``is_valid()``, e um retrato tirado depois
já sairia igual ao novo.
"""
from datetime import date

from .models import ActivityChange

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


def _display(act, name):
    value = getattr(act, name)
    if value is None or value == "":
        return ""
    if act._meta.get_field(name).choices:
        return getattr(act, f"get_{name}_display")()
    if isinstance(value, date):
        return f"{value:%d/%m/%Y}"
    return str(value)


def snapshot(act):
    return {name: _display(act, name) for name, _, _ in TRACKED}


def diff(act, before):
    """Campos que mudaram desde ``before`` (um ``snapshot``)."""
    out = []
    for name, label, family in TRACKED:
        after = _display(act, name)
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


def record(act, user, family_saw, fields):
    """Grava a alteração se houver o que gravar. Rascunho não tem histórico."""
    if not fields or act.status == act.Status.DRAFT:
        return None
    return ActivityChange.objects.create(
        activity=act, changed_by=user, family_saw=family_saw, fields=fields
    )


def summary(fields, family_only=False):
    """"Instruções, data de entrega" — para a auditoria e as telas."""
    labels = [f["label"] for f in fields if f.get("family") or not family_only]
    return ", ".join(dict.fromkeys(labels)).lower()
