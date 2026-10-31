"""Tipologias por componente (escolha metodológica do projeto, a validar com professores).

Cada área tem formas próprias de errar e de evidenciar aprendizagem: não há uma
tipologia única. Arte, Educação Física e Ensino Religioso NÃO têm tipologia de
erro de propósito: o projeto não classifica gosto, talento, desempenho físico
isolado nem crença (Prompt 16, seções 6.6 a 6.8).
"""

ERROR_TYPES = {
    "Matemática": [
        ("calculo", "Erro de cálculo"),
        ("conceitual", "Erro conceitual"),
        ("enunciado", "Interpretação do enunciado"),
        ("estrategia", "Escolha da estratégia"),
        ("representacao", "Representação matemática"),
    ],
    "Língua Portuguesa": [
        ("compreensao", "Compreensão do texto"),
        ("organizacao", "Organização das ideias"),
        ("genero", "Adequação ao gênero e à finalidade"),
        ("convencoes", "Convenções da escrita (não indica falta de compreensão)"),
    ],
    "Ciências": [
        ("conceito", "Conceito científico"),
        ("procedimento", "Procedimento investigativo"),
        ("dados", "Interpretação de dados ou evidências"),
        ("argumentacao", "Argumentação com base em evidências"),
    ],
    "História": [
        ("temporalidade", "Temporalidade e cronologia"),
        ("fonte", "Leitura de fonte"),
        ("contexto", "Contextualização e causalidade"),
        ("argumentacao", "Argumentação histórica"),
    ],
    "Geografia": [
        ("espacial", "Orientação e localização"),
        ("cartografia", "Leitura cartográfica e escala"),
        ("conceito", "Conceito geográfico"),
        ("dados", "Interpretação de dados"),
    ],
    "Língua Inglesa": [
        ("compreensao", "Compreensão"),
        ("vocabulario", "Vocabulário"),
        ("estrutura", "Estrutura da língua"),
        ("interacao", "Interação comunicativa"),
    ],
}
NO_ERROR_TYPING = {"Arte", "Educação Física", "Ensino Religioso"}
DEFAULT = [
    ("enunciado", "Compreensão do enunciado"),
    ("conceito", "Conceito"),
    ("procedimento", "Procedimento"),
]


def error_choices(component):
    if component in NO_ERROR_TYPING:
        return []
    return ERROR_TYPES.get(component, DEFAULT)


def error_label(component, code):
    return dict(ERROR_TYPES.get(component, DEFAULT) + DEFAULT).get(code, code)
