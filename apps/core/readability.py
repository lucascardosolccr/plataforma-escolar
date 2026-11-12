"""Legibilidade de textos em português (Python puro, custo zero, sem dado de aluno).

Para que a escola escreva enunciados e recados que crianças e famílias de fato entendam. Opera só sobre o
texto que o adulto escreveu — não toca em dado pessoal.

Método: **Índice de Facilidade de Leitura** (adaptação de Martins, Ghiraldelo, Nunes & Oliveira, 1996, do
Flesch Reading Ease, 1948, para o português do Brasil):

    IFL = 248,835 − 1,015 × (palavras / frases) − 84,6 × (sílabas / palavra)

Quanto maior, mais fácil. As faixas (muito fácil … muito difícil) e o ano escolar aproximado são **referência**,
não medida exata: o índice ignora vocabulário conhecido, ordem das ideias e contexto. Frase muito longa é
sinalizada à parte porque é a causa mais comum, e mais fácil de corrigir, de um texto difícil.

A contagem de sílabas é por grupos de vogais (heurística): basta para o índice, que é robusto a pequenos erros,
e não depende de dicionário.
"""

import re

VOWELS = "aeiouáéíóúâêôàãõäëïöüy"
_WORD = re.compile(r"[0-9A-Za-zÀ-ÿ]+")
_SENTENCE = re.compile(r"[.!?…]+|\n+")
LONG_SENTENCE = 25   # palavras numa frase acima disto: candidata a dividir
MIN_WORDS = 10       # abaixo disto o índice não diz nada


def syllables(word):
    """Estimativa de sílabas: número de grupos de vogais. Ao menos 1 se houver vogal."""
    groups, in_vowel = 0, False
    for ch in word.lower():
        is_vowel = ch in VOWELS
        if is_vowel and not in_vowel:
            groups += 1
        in_vowel = is_vowel
    return groups


def _band(score):
    """(faixa, ano escolar aproximado) do IFL. Convenção, não régua."""
    if score >= 75:
        return "muito fácil", "até cerca do 5º ano"
    if score >= 50:
        return "fácil", "6º ao 9º ano"
    if score >= 25:
        return "difícil", "ensino médio"
    return "muito difícil", "ensino superior"


def analyze(text):
    """Legibilidade de ``text``. Devolve None quando não há texto; ``{"enough": False, ...}`` quando há texto
    curto demais para o índice; senão o índice, as faixas e as frases longas."""
    text = (text or "").strip()
    if not text:
        return None
    sentences = [s.strip() for s in _SENTENCE.split(text) if s.strip()]
    if not sentences:
        sentences = [text]
    words = _WORD.findall(text)
    n_words, n_sentences = len(words), len(sentences)
    if n_words < MIN_WORDS:
        return {"enough": False, "words": n_words, "min_words": MIN_WORDS}
    n_syll = sum(syllables(w) for w in words)
    wps = n_words / n_sentences
    spw = n_syll / n_words
    raw = 248.835 - 1.015 * wps - 84.6 * spw
    score = max(0.0, min(100.0, raw))
    band, grade = _band(score)
    long_sentences = [s for s in sentences if len(_WORD.findall(s)) > LONG_SENTENCE]
    return {
        "enough": True, "score": round(score, 1), "band": band, "grade": grade,
        "words": n_words, "sentences": n_sentences, "syllables": n_syll,
        "words_per_sentence": round(wps, 1), "syllables_per_word": round(spw, 2),
        "long_sentences": long_sentences, "long_count": len(long_sentences),
    }
