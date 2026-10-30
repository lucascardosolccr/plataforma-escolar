"""Leitura de identificadores vindos da URL.

Um ``?estudante=abc`` ia direto para ``filter(pk=...)`` e derrubava a página
com erro 500 em nove listagens. Identificador inválido agora é tratado como
filtro ausente — o mesmo que acontece com uma data inválida.
"""


def id_param(request, name, source=None):
    """O valor de ``name`` se for um identificador numérico positivo, senão None.

    Devolve o texto, e não um ``int``, porque os templates comparam o filtro
    selecionado como texto (``request.GET.turma == c.pk|stringformat:'s'``).
    """
    data = request.GET if source is None else source
    value = (data.get(name) or "").strip()
    if value.isdigit() and value.isascii() and int(value) > 0:
        return value
    return None


def name_q(text, prefix=""):
    """Filtro de busca por nome: cada palavra precisa aparecer no nome ou no sobrenome.

    ``name_q("ana silva", "student__")`` acha "Ana Maria da Silva". Texto
    vazio não filtra nada. Limitado a 5 palavras e 60 caracteres, porque o
    valor vem da URL.
    """
    from django.db.models import Q

    q = Q()
    for term in (text or "")[:60].split()[:5]:
        q &= Q(**{f"{prefix}first_name__icontains": term}) | Q(**{f"{prefix}last_name__icontains": term})
    return q
