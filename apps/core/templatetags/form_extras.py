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
    # Liga erro e ajuda ao campo para leitores de tela: ao focar o campo, a
    # pessoa ouve também a orientação e o que está errado.
    descritos = []
    if field.errors:
        attrs["aria-invalid"] = "true"
        descritos.append(f"{field.auto_id}_erro")
    if field.help_text:
        descritos.append(f"{field.auto_id}_ajuda")
    if descritos:
        attrs["aria-describedby"] = " ".join(descritos)
    return field.as_widget(attrs=attrs)


@register.filter
def is_wide(field):
    """Campo que ocupa a linha inteira na grade do formulário (texto longo,
    arquivo, múltipla escolha). Os curtos ficam lado a lado em telas largas."""
    if not hasattr(field, "field"):
        return True
    widget = field.field.widget
    return isinstance(
        widget,
        (forms.Textarea, forms.FileInput, forms.CheckboxSelectMultiple,
         forms.SelectMultiple, forms.RadioSelect),
    )


@register.filter
def is_checkbox(field):
    return hasattr(field, "field") and isinstance(
        field.field.widget, forms.CheckboxInput
    )


@register.filter
def is_choice_group(field):
    """Grupo de opções (rádios ou caixas múltiplas): vira fieldset com uma
    opção por linha. Renderizado pelo widget padrão, ficava espremido."""
    return hasattr(field, "field") and isinstance(
        field.field.widget, (forms.RadioSelect, forms.CheckboxSelectMultiple)
    )


@register.filter
def choice_options(field):
    """Opções do grupo com a classe do Bootstrap em cada caixa."""
    css = "form-check-input" + (" is-invalid" if field.errors else "")
    options = []
    for sub in field.subwidgets:
        sub.data["attrs"] = {**sub.data["attrs"], "class": css}
        options.append(sub)
    return options
