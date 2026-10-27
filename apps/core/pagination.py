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
