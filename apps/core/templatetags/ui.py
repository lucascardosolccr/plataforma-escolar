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


@register.simple_tag
def avatar(person, size=""):
    """Foto de identificação (ou iniciais) de um estudante ou de uma conta.

    ``person``: ``Student`` ou ``User``. A imagem sai por views que conferem
    permissão (nunca por URL pública de mídia). ``size``: "", "lg" ou "xl".
    """
    from django.urls import reverse
    from django.utils.html import format_html

    from apps.core.models import STAFF_ROLES, Role

    url = None
    if person is None:
        return ""
    if hasattr(person, "enrollments"):  # Student
        if person.photo:
            url = reverse("student_photo", args=[person.pk])
        first, last = person.first_name, person.last_name
    else:
        if person.role in [r.value for r in STAFF_ROLES] and person.photo:
            url = reverse("user_photo", args=[person.pk])
        elif person.role == Role.RESPONSAVEL.value:
            profile = getattr(person, "guardian_profile", None)
            if profile is not None and profile.photo:
                url = reverse("guardian_photo", args=[person.pk])
        first, last = person.first_name or person.username, person.last_name
    css = f"avatar-photo {size}".strip()
    if url:
        return format_html('<img src="{}" alt="" class="{}" loading="lazy">', url, css)
    initials = f"{(first or '?')[:1]}{(last or '')[:1]}".upper()
    return format_html('<span class="avatar{}" aria-hidden="true">{}</span>',
                       " avatar-xl" if size in ("lg", "xl") else "", initials)
