from django import template

register = template.Library()


@register.filter
def picker_rows(form):
    """Grupos do seletor como (rótulo, itens, endereço sob demanda ou None, quantidade).

    ``curriculum_groups`` continua em pares (rótulo, itens); os grupos sob demanda estão em
    ``curriculum_lazy`` (CurriculumFormMixin). Formulários que montam a lista à mão não têm esse atributo."""
    lazy = getattr(form, "curriculum_lazy", {}) or {}
    rows = []
    for label, items in getattr(form, "curriculum_groups", []) or []:
        url, count = lazy.get(label, (None, len(items)))
        rows.append((label, items, url, count))
    return rows
