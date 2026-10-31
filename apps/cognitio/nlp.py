"""Análise de produções escritas por regras explícitas (PLN sem serviço pago e sem modelo opaco).

O analisador aponta INDÍCIOS observáveis, sempre com o trecho que os sustenta,
o grau de confiança (nunca "alta") e a exigência de revisão docente. Ele:

- não atribui nota, não substitui a avaliação do professor;
- não avalia ortografia nem norma-padrão (para não confundir convenção da escrita
  com compreensão, nem penalizar variação linguística, alfabetização em curso ou
  necessidades específicas de comunicação);
- muda o que observa conforme o componente (Língua Portuguesa: organização,
  coesão, argumentação; Matemática: procedimento, justificativa, resposta;
  Ciências: conceitos, evidência, causa; História: tempo, sujeitos, fontes;
  Geografia: espaço, escala, sociedade-natureza).

Também sugere habilidades da BNCC para uma atividade ou avaliação (TF-IDF sobre o
texto oficial das habilidades do componente e do ano), sempre para revisão.
"""

import math
import re
import unicodedata
from collections import Counter

ENGINE_VERSION = "regras-1.0"

CONNECTIVES = {
    "adição": ["além disso", "também", "ainda", "e ainda", "bem como"],
    "oposição": ["mas", "porém", "contudo", "entretanto", "no entanto", "embora", "apesar de", "todavia"],
    "causa": ["porque", "pois", "já que", "visto que", "uma vez que", "devido a", "por causa de"],
    "conclusão": ["portanto", "por isso", "assim", "logo", "então", "consequentemente", "dessa forma", "concluindo"],
    "tempo e sequência": ["depois", "antes", "quando", "enquanto", "em seguida", "por fim", "primeiro", "finalmente",
                          "inicialmente"],
    "exemplificação": ["por exemplo", "como exemplo", "isto é", "ou seja"],
}
OPINION = ["eu acho", "na minha opinião", "acredito", "defendo", "penso que", "considero", "concordo", "discordo"]
EVIDENCE = ["observamos", "observei", "o resultado", "os resultados", "os dados", "medimos", "registramos",
            "o experimento", "percebemos", "comprovamos", "de acordo com"]
TIME = ["século", "antes", "depois", "época", "período", "anos", "durante", "naquela", "atualmente", "passado"]
SOURCES = ["fonte", "documento", "carta", "jornal", "relato", "imagem", "pintura", "segundo", "de acordo com"]
SUBJECTS_H = ["povo", "povos", "indígena", "trabalhador", "rei", "governo", "escravizado", "imigrante", "mulheres",
              "grupo", "sociedade"]
SPACE = ["norte", "sul", "leste", "oeste", "mapa", "região", "escala", "localiza", "território", "paisagem", "lugar",
         "cidade", "campo", "rio", "relevo", "clima"]
STOP = set("""a o e é de da do das dos em no na nos nas um uma uns umas para por com sem como que se ao aos à às ou
seu sua seus suas entre sobre até mais menos isso esta este estes estas esse essa esses essas também já não sim
ele ela eles elas eu nós você vocês me te lhe nos foi era são ser ter tem mas muito muita muitos muitas quando
onde qual quais cada mesmo mesma tipo pelo pela pelos pelas aquele aquela então porque pois""".split())


def plain(t):
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")


def words(t):
    return re.findall(r"[a-zà-ú]+", (t or "").lower())


def sentences(t):
    parts = re.split(r"(?<=[.!?])\s+|\n+", (t or "").strip())
    return [p.strip() for p in parts if len(p.strip()) > 1]


def stem(w):
    w = plain(w)
    for suf in ("mente", "coes", "cao", "oes", "aes", "ais", "eis", "res", "as", "os", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def _find(text, terms):
    """Termos encontrados e a primeira frase que contém cada um."""
    sents = sentences(text)
    found = []
    for term in terms:
        pt = plain(term)
        rx = re.compile(r"\b" + re.escape(pt) + r"\b")
        for s in sents:
            if rx.search(plain(s)):
                found.append((term, s))
                break
    return found


def mattr(ws, window=40):
    """Diversidade lexical média em janelas móveis (MATTR), menos sensível ao tamanho."""
    if len(ws) < 10:
        return None
    if len(ws) <= window:
        return len(set(ws)) / len(ws)
    vals = [len(set(ws[i:i + window])) / window for i in range(len(ws) - window + 1)]
    return sum(vals) / len(vals)


def _signal(key, label, ok, detail, excerpt="", kind="indicio"):
    return {"key": key, "label": label, "status": "evidenciado" if ok else "nao_evidenciado", "detail": detail,
            "excerpt": excerpt[:240], "kind": kind}


def analyze(text, component="", prompt_text="", expected_concepts="", genre=""):
    ws = words(text)
    sents = sentences(text)
    paras = [p for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]
    n = len(ws)
    metrics = {"palavras": n, "frases": len(sents), "paragrafos": len(paras),
               "media_palavras_por_frase": round(n / len(sents), 1) if sents else 0,
               "diversidade_lexical": round(mattr(ws), 2) if mattr(ws) is not None else None}
    signals, difficulties, feedback = [], [], []
    # Conceitos esperados (todos os componentes).
    concepts = [c.strip() for c in (expected_concepts or "").split(",") if c.strip()]
    if concepts:
        stems_text = {stem(w) for w in ws}
        hits, misses = [], []
        for c in concepts:
            c_stems = {stem(w) for w in words(c) if plain(w) not in STOP}
            if c_stems and c_stems <= stems_text:
                ex = next((s for s in sents if c_stems <= {stem(w) for w in words(s)}), "")
                hits.append((c, ex))
            else:
                misses.append(c)
        for c, ex in hits:
            signals.append(_signal(f"conceito:{plain(c)[:30]}", f"Conceito presente: {c}", True,
                                   "O termo (ou variação) aparece no texto. Presença não garante uso correto.", ex,
                                   "conceito"))
        for c in misses:
            signals.append(_signal(f"conceito:{plain(c)[:30]}", f"Conceito não encontrado: {c}", False,
                                   "Pode ter sido expresso com outras palavras: confira a leitura.", "", "conceito"))
        if misses:
            difficulties.append(f"Conceitos esperados não localizados: {', '.join(misses)}.")
            feedback.append(f"Peça que o estudante explique com as próprias palavras: {', '.join(misses[:3])}.")
    # Relação com o enunciado.
    if prompt_text:
        pw = {stem(w) for w in words(prompt_text) if plain(w) not in STOP and len(w) > 3}
        tw = {stem(w) for w in ws}
        overlap = sorted(pw & tw)
        ok = bool(pw) and len(overlap) / len(pw) >= 0.25
        signals.append(_signal("enunciado", "Retoma termos do enunciado", ok,
                               f"{len(overlap)} de {len(pw)} termos do enunciado aparecem na resposta"
                               f"{': ' + ', '.join(overlap[:8]) if overlap else ''}. Indício de que a pergunta foi "
                               "considerada; não comprova compreensão."))
        if not ok:
            difficulties.append("A resposta retoma poucos termos do enunciado: verificar se a pergunta foi compreendida.")
    comp = component or ""
    if comp in ("Língua Portuguesa", "Língua Inglesa", "") or genre:
        found = {cat: _find(text, terms) for cat, terms in CONNECTIVES.items()}
        cats = [c for c, f in found.items() if f]
        ex = next((f[0][1] for f in found.values() if f), "")
        signals.append(_signal("coesao", "Articuladores entre ideias (coesão)", len(cats) >= 2,
                               f"Tipos de articulador encontrados: {', '.join(cats) or 'nenhum'}.", ex))
        if len(cats) < 2 and n >= 40:
            feedback.append("Sugira conectivos para ligar as ideias (por exemplo: porque, por isso, além disso, mas).")
        signals.append(_signal("paragrafos", "Organização em parágrafos", len(paras) >= 2 or n < 60,
                               f"{len(paras)} parágrafo(s) para {n} palavras."))
        long_s = [s for s in sents if len(words(s)) > 35]
        signals.append(_signal("frases", "Frases de extensão controlada", not long_s,
                               f"{len(long_s)} frase(s) com mais de 35 palavras." if long_s else "Nenhuma frase muito longa.",
                               long_s[0] if long_s else ""))
        reps = [w for w, c in Counter(stem(w) for w in ws if plain(w) not in STOP and len(w) > 3).items() if c >= 4]
        signals.append(_signal("repeticao", "Variedade de vocabulário", not reps,
                               f"Palavras repetidas 4 vezes ou mais: {', '.join(reps[:5])}." if reps
                               else "Sem repetições excessivas.", kind="indicio"))
        opinion = _find(text, OPINION)
        if genre and plain(genre).startswith(("argument", "opiniao", "artigo")) or opinion:
            causes = found.get("causa") or found.get("conclusão")
            signals.append(_signal("argumentacao", "Posicionamento sustentado por razão", bool(opinion and causes),
                                   "Há posicionamento e marcador de causa ou conclusão." if opinion and causes else
                                   "Posicionamento sem justificativa explícita, ou justificativa sem posicionamento.",
                                   (causes or opinion or [("", "")])[0][1]))
    if comp == "Matemática":
        nums = re.findall(r"\d+(?:[.,]\d+)?", text or "")
        ops = re.findall(r"[+\-x×*/÷=]", text or "")
        steps = [s for s in (text or "").split("\n") if re.search(r"\d", s)]
        signals.append(_signal("procedimento", "Procedimento registrado", len(ops) >= 1 and len(steps) >= 2,
                               f"{len(nums)} número(s), {len(ops)} operação(ões), {len(steps)} linha(s) com cálculo.",
                               steps[0] if steps else ""))
        just = _find(text, ["porque", "pois", "então", "logo", "como", "assim"])
        signals.append(_signal("justificativa", "Justificativa da estratégia", bool(just),
                               "Há explicação em palavras do caminho escolhido." if just else
                               "Só cálculo, sem explicação: peça para justificar.", just[0][1] if just else ""))
        answer = re.search(r"(resposta|r:|resultado|total)", plain(text))
        signals.append(_signal("resposta", "Resposta comunicada", bool(answer),
                               "Há uma resposta explícita ao problema." if answer else "Não há frase de resposta."))
        if not just:
            feedback.append("Peça que o estudante explique por que escolheu a operação (o erro pode ser de interpretação, "
                            "não de cálculo).")
    if comp == "Ciências":
        ev = _find(text, EVIDENCE)
        cause = _find(text, CONNECTIVES["causa"] + CONNECTIVES["conclusão"])
        signals.append(_signal("evidencia", "Uso de evidência ou observação", bool(ev),
                               "Menciona observação, dado ou resultado." if ev else "Não cita o que foi observado.",
                               ev[0][1] if ev else ""))
        signals.append(_signal("causalidade", "Explicação causal", bool(cause),
                               "Relaciona causa e efeito." if cause else "Descreve sem explicar o porquê.",
                               cause[0][1] if cause else ""))
    if comp == "História":
        t = _find(text, TIME) or ([("ano", s) for s in sents if re.search(r"\b1\d{3}\b|\b20\d{2}\b", s)][:1])
        sj = _find(text, SUBJECTS_H)
        src = _find(text, SOURCES)
        signals.append(_signal("tempo", "Referência temporal", bool(t), "Situa no tempo." if t else
                               "Sem marcação de tempo.", t[0][1] if t else ""))
        signals.append(_signal("sujeitos", "Sujeitos históricos identificados", bool(sj), "Nomeia grupos ou agentes."
                               if sj else "Não identifica quem age.", sj[0][1] if sj else ""))
        signals.append(_signal("fontes", "Menção a fontes", bool(src), "Refere-se a fontes ou documentos." if src else
                               "Não menciona fontes.", src[0][1] if src else ""))
    if comp == "Geografia":
        sp = _find(text, SPACE)
        signals.append(_signal("espaco", "Vocabulário espacial e geográfico", len(sp) >= 2,
                               f"Termos: {', '.join(t for t, _ in sp[:6]) or 'nenhum'}.", sp[0][1] if sp else ""))
        cause = _find(text, CONNECTIVES["causa"] + CONNECTIVES["conclusão"])
        signals.append(_signal("relacao", "Relação entre elementos (sociedade, natureza, lugar)", bool(cause),
                               "Explica relações." if cause else "Lista elementos sem relacioná-los.",
                               cause[0][1] if cause else ""))
    confidence = "baixa" if n < 40 else "média"
    notes = ["Indícios de regras explícitas sobre o texto; revisão do professor é obrigatória.",
             "Ortografia e norma-padrão não são analisadas, para não confundir convenção da escrita com compreensão "
             "nem penalizar variação linguística ou alfabetização em curso.",
             "Nenhuma nota é atribuída."]
    if n < 40:
        notes.append("Texto curto: poucos indícios são confiáveis.")
    return {"engine": ENGINE_VERSION, "metrics": metrics, "signals": signals, "difficulties": difficulties,
            "feedback": feedback, "confidence": confidence, "review_required": True, "notes": notes}


# ------------------------------------------------------------------ sugestão de habilidades
def _tf(ws):
    c = Counter(ws)
    total = sum(c.values()) or 1
    return {w: v / total for w, v in c.items()}


def suggest_skills(text, school, component, year, limit=5):
    """Habilidades da BNCC mais parecidas com o texto (TF-IDF + cosseno), para revisão."""
    from apps.curriculum.models import CurriculumItem

    if not component or not (text or "").strip():
        return []
    items = list(CurriculumItem.for_pair(school, component, year))
    if not items:
        return []
    docs = {i.pk: [stem(w) for w in words(i.text + " " + (i.knowledge_object or "")) if plain(w) not in STOP and len(w) > 3]
            for i in items}
    df = Counter(w for ws in docs.values() for w in set(ws))
    N = len(docs)
    idf = {w: math.log((N + 1) / (d + 1)) + 1 for w, d in df.items()}

    def vec(ws):
        tf = _tf(ws)
        return {w: tf[w] * idf.get(w, 0) for w in tf}

    q = vec([stem(w) for w in words(text) if plain(w) not in STOP and len(w) > 3])
    qn = math.sqrt(sum(v * v for v in q.values())) or 1
    out = []
    for it in items:
        d = vec(docs[it.pk])
        dn = math.sqrt(sum(v * v for v in d.values())) or 1
        score = sum(q[w] * d.get(w, 0) for w in q) / (qn * dn)
        if score > 0.05:
            shared = sorted(set(q) & set(d), key=lambda w: -q[w] * d[w])[:5]
            out.append({"item": it, "score": round(score, 2), "shared": shared})
    out.sort(key=lambda r: -r["score"])
    return out[:limit]
