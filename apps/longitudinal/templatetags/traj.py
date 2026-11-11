from django import template

register = template.Library()


@register.filter
def prob(value, places=0):
    """Proporção de 0 a 1 como percentual ("34%"); sem dado, "—"."""
    if value is None or value == "":
        return "—"
    return f"{100 * float(value):.{int(places)}f}".replace(".", ",") + "%"


@register.filter
def dec(value, places=2):
    if value is None or value == "":
        return "—"
    return f"{float(value):.{int(places)}f}".replace(".", ",")


@register.filter
def at(seq, index):
    try:
        return seq[int(index)]
    except (IndexError, TypeError, ValueError, KeyError):
        return None
