"""Componentes de interface usados pelos templates.

``{% icon "house" %}`` desenha um ícone do sprite local (static/icons). O
ícone é sempre decorativo (aria-hidden): quem precisa de nome acessível é o
botão ou link que o contém.
"""

from django import template
from django.templatetags.static import static
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def icon(name, extra_class=""):
    href = static("icons/sprite.svg")
    css = f"ds-icon {extra_class}".strip()
    return format_html(
        '<svg class="{}" aria-hidden="true" focusable="false"><use href="{}#i-{}"></use></svg>',
        css, href, name,
    )


@register.filter
def count_where(items, key):
    """Quantos itens têm ``key`` verdadeiro: ``{{ medias|count_where:"below" }}``."""
    return sum(1 for item in items or () if item.get(key))


@register.simple_tag(takes_context=True)
def sort_th(context, sort, key, label, css=""):
    """Cabeçalho de coluna que ordena a lista inteira no servidor.

    ``{% sort_th sort "data" "Data" "text-end" %}`` gera o <th> com link que
    preserva os filtros da URL, volta à primeira página e informa
    ``aria-sort`` ao leitor de tela.
    """
    from django.http import QueryDict

    from apps.core.pagination import PAGE_PARAM, SORT_PARAM

    request = context["request"]
    params = request.GET.copy() if request is not None else QueryDict(mutable=True)
    params[SORT_PARAM] = sort.link(key)
    params.pop(PAGE_PARAM, None)
    aria = sort.aria(key)
    state = {"ascending": " (ordem crescente)", "descending": " (ordem decrescente)"}.get(aria, "")
    return format_html(
        '<th scope="col"{}{}><a class="th-sort" href="?{}" title="Ordenar por {}">{}<span class="visually-hidden">{}</span>{}</a></th>',
        format_html(' class="{}"', css) if css else "",
        format_html(' aria-sort="{}"', aria) if aria else "",
        params.urlencode(), label.lower(), label, state, icon("arrow-up-down"),
    )
