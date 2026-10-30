"""Paginação das listagens.

Antes as listas eram cortadas com uma fatia (`qs[:200]`), o que escondia
silenciosamente qualquer registro além do limite: numa escola real, com
centenas de estudantes ou de atividades, o usuário não tinha como saber que
havia mais nem como chegar lá.
"""

from django.core.paginator import Paginator

#: Linhas por página nas tabelas. Mantém a página leve sem obrigar a paginar
#: a toda hora nas escolas pequenas.
PAGE_SIZE = 25

#: Parâmetro na URL. Em português, para acompanhar o resto das rotas.
PAGE_PARAM = "pagina"


def paginate(request, object_list, per_page=PAGE_SIZE):
    """Devolve o ``Page`` pedido na querystring.

    ``Paginator.get_page`` já tolera valor ausente, não numérico ou fora da
    faixa — devolve a primeira ou a última página em vez de levantar erro.
    Isso importa porque o número vem da URL e pode ser digitado à mão.

    O ``Page`` é iterável e responde a ``len()``, então o template continua
    percorrendo o mesmo nome de contexto de antes.
    """
    return Paginator(object_list, per_page).get_page(request.GET.get(PAGE_PARAM))


SORT_PARAM = "ordem"


class Sort:
    """Ordenação de uma lista paginada pela coluna escolhida, no servidor.

    ``columns`` liga o nome usado na URL (``?ordem=data`` ou ``?ordem=-data``)
    aos campos do banco. Só nomes da lista são aceitos: o valor vem da URL
    e nunca chega cru ao ``order_by``. Ordenar no servidor vale para a lista
    inteira; ordenar no navegador só reordenaria a página visível.
    """

    def __init__(self, request, columns, default):
        self.columns = columns
        raw = request.GET.get(SORT_PARAM, "")
        key = raw.lstrip("-")
        if key not in columns:
            raw, key = default, default.lstrip("-")
        self.key = key
        self.descending = raw.startswith("-")

    def apply(self, qs):
        fields = self.columns[self.key]
        if isinstance(fields, str):
            fields = (fields,)
        order = [f"-{f}" if self.descending else f for f in fields]
        return qs.order_by(*order, "-pk" if self.descending else "pk")

    def link(self, key):
        """Valor de ``ordem`` para o cabeçalho: inverte se já é a coluna atual."""
        if key == self.key:
            return key if self.descending else f"-{key}"
        return key

    def aria(self, key):
        if key != self.key:
            return ""
        return "descending" if self.descending else "ascending"
