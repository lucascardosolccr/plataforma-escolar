from django import template

register = template.Library()


@register.filter
def getitem(mapping, key):
    """Acessa um campo de formulário por nome variável: {{ form|getitem:field_name }}."""
    try:
        return mapping[key]
    except (KeyError, TypeError):
        return None