"""Aplica as classes de formulário do Bootstrap aos campos do Django.

Os widgets do Django não conhecem o Bootstrap, e o projeto renderiza os
formulários por um partial compartilhado. Em vez de repetir ``attrs={"class":
...}`` em cada campo de cada formulário, o partial chama ``bs`` e a classe
certa é escolhida pelo tipo de widget.
"""

from django import forms
from django import template

register = template.Library()


def _widget_class(widget):
    if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect)):
        return "form-check-input"
    if isinstance(widget, forms.CheckboxSelectMultiple):
        return "form-check-input"
    if isinstance(widget, forms.Select):
        return "form-select"
    if isinstance(widget, forms.FileInput):
        return "form-control"
    if isinstance(widget, forms.HiddenInput):
        return ""
    return "form-control"


@register.filter
def bs(field):
    """Rende o campo com a classe do Bootstrap e marca erros com is-invalid."""
    if not hasattr(field, "as_widget"):
        return field
    widget = field.field.widget
    css = _widget_class(widget)
    if not css:
        return field.as_widget()
    existing = widget.attrs.get("class", "")
    classes = f"{existing} {css}".strip()
    if field.errors:
        classes = f"{classes} is-invalid"
    attrs = {"class": classes}
    # Liga a mensagem de erro ao campo para leitores de tela.
    if field.errors:
        attrs["aria-invalid"] = "true"
        attrs["aria-describedby"] = f"{field.auto_id}_erro"
    return field.as_widget(attrs=attrs)


@register.filter
def is_checkbox(field):
    return hasattr(field, "field") and isinstance(
        field.field.widget, forms.CheckboxInput
    )
