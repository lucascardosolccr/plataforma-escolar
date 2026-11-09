"""Correção de um caso do Django que virava erro 500.

``ModelMultipleChoiceField`` confere cada valor com ``filter(pk=valor)`` (o Django já trata número fora da faixa
do banco) e depois busca todos com ``filter(pk__in=valores)``, que no SQLite levanta ``OverflowError`` para
um número maior que 2^63 - 1. Um formulário com lista de estudantes enviado com ``99999999999999999999``
derrubava a página em vez de dizer "opção inválida". Vale para todos os formulários de uma vez, inclusive os
campos muitos-para-muitos que o ModelForm gera sozinho.
"""

from django.core.exceptions import ValidationError
from django.forms.models import ModelMultipleChoiceField

from .params import MAX_ID

_original_check_values = ModelMultipleChoiceField._check_values


def _check_values(self, value):
    for pk in value or ():
        text = str(pk).strip()
        if text.isascii() and text.lstrip("-").isdigit() and abs(int(text)) > MAX_ID:
            raise ValidationError(self.error_messages["invalid_pk_value"], code="invalid_pk_value",
                                  params={"pk": text[:30]})
    return _original_check_values(self, value)


def install():
    if ModelMultipleChoiceField._check_values is not _check_values:
        ModelMultipleChoiceField._check_values = _check_values
