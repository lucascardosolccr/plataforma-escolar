"""Números em texto, no padrão brasileiro.

Nas telas, os números passados ao modelo de página já saem com vírgula decimal (localização do Django).
O problema são os textos montados em Python (avisos, explicações, rótulos), que saíam com ponto: "chegou a
25.3% de faltas". Use estas funções sempre que um número com casas decimais entrar numa frase.
"""


def dec(value, places=2):
    """'0,42'; sem valor, '—' (ausência de dado nunca vira zero)."""
    if value is None:
        return "—"
    return f"{float(value):.{places}f}".replace(".", ",")


def pct(value, places=1):
    """'25,3%'; sem valor, '—'."""
    return "—" if value is None else dec(value, places) + "%"
