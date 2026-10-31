"""Extrai objetivos e conteúdos do Currículo em Movimento do DF (EF, 2ª ed., 2018).

Uso: python -I cm_extract.py <cm.pdf> <saida.json>

PyMuPDF dá posição, negrito e marcador de cada linha; o texto com acentos vem do
xpdf pdftotext (as fontes do PDF não têm tabela ToUnicode e o PyMuPDF devolve U+FFFD).
"""
import json
import re
import subprocess
import sys
import unicodedata

import fitz

SRC, OUT = sys.argv[1], sys.argv[2]
FFFD = "�"

SIDE_COMPONENTS = [
    ("PORTUGUESA", "Língua Portuguesa", "LP"), ("MATEMATICA", "Matemática", "MA"),
    ("CIENCIAS DA NATUREZA", "Ciências", "CI"), ("GEOGRAFIA", "Geografia", "GE"), ("HISTORIA", "História", "HI"),
    ("RELIGIOSO", "Ensino Religioso", "ER"), ("ARTE", "Arte", "AR"), ("EDUCACAO FISICA", "Educação Física", "EF"),
    ("ESTRANGEIRA", "Língua Inglesa", "LI"),
]


def xpdf_page(pno):
    r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-f", str(pno), "-l", str(pno), SRC, "-"],
                       capture_output=True)
    return r.stdout.decode("utf-8", "replace")


def norm_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def fix_text(raw, page_text, cache):
    """Troca U+FFFD pelo caractere certo, achando a mesma linha no texto do xpdf."""
    t = norm_ws(raw)
    if t.startswith("◦ "):
        return "◦ " + fix_text(t[2:], page_text, cache)
    if FFFD not in t:
        return t
    if t in cache:
        return cache[t]
    parts = [re.escape(p) for p in t.split(FFFD)]
    pat = "(?:\\S)".join(p.replace("\\ ", "\\s+") for p in parts)
    found = set(m.group(0) for m in re.finditer(pat, page_text))
    fixed = norm_ws(sorted(found)[0]) if len(found) == 1 else None
    if fixed is None and found:
        fixed = norm_ws(sorted(found)[0])  # mesmo padrão em vários lugares: escolhe o primeiro
    cache[t] = fixed or t
    return cache[t]


def plain(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.upper()) if unicodedata.category(c) != "Mn")


doc = fitz.open(SRC)
items = []
state = {}  # (comp, arte_lang, year, role) -> último item, para continuar entre páginas
unit_state = {}
obj_units = {}
stats = {"pages_table": 0, "pages_skipped": 0, "fffd_left": 0}
arte_lang = ""

for pidx in range(doc.page_count):
    page = doc[pidx]
    W = page.rect.width
    d = page.get_text("dict")
    lines = []
    for b in d["blocks"]:
        for l in b.get("lines", []):
            spans = [s for s in l["spans"] if s["text"].strip()]
            if not spans:
                continue
            x0 = min(s["bbox"][0] for s in spans)
            y0 = min(s["bbox"][1] for s in spans)
            x1 = max(s["bbox"][2] for s in spans)
            y1 = max(s["bbox"][3] for s in spans)
            bullet = spans[0]["font"].startswith("Symbol") or spans[0]["text"].strip() in ("•", "·")
            txt_spans = spans[1:] if bullet and spans[0]["font"].startswith("Symbol") else spans
            if txt_spans and txt_spans[0]["font"].startswith("CourierNew") and txt_spans[0]["text"].strip() == "o":
                txt_spans = txt_spans[1:]  # subitem (marcador "o" em Courier): continua o item, com "◦"
                text = "◦ " + "".join(s["text"] for s in txt_spans).strip()
            else:
                text = "".join(s["text"] for s in txt_spans)
            if bullet and text.strip()[:1] in ("•", "·"):
                text = text.strip()[1:]
            bold = all((s["flags"] & 16) or "Bold" in s["font"] for s in txt_spans) if txt_spans else False
            vertical = l["dir"][0] < 0.5
            lines.append({"x0": x0, "x1": x1, "y0": y0, "y1": y1, "text": text, "bold": bold,
                          "bullet": bullet, "vertical": vertical})
    heads = [l for l in lines if l["bold"] and re.fullmatch(r"OBJETIVOS|CONTE.DOS", norm_ws(l["text"]))]
    years = [l for l in lines if l["bold"] and re.fullmatch(r"(\d).?\s*ANO", norm_ws(l["text"]))]
    if not heads or not years:
        stats["pages_skipped"] += 1
        if any(l["vertical"] and l["x0"] > W - 70 for l in lines):
            stats.setdefault("tab_without_header", []).append(pidx + 1)
        continue
    stats["pages_table"] += 1
    page_text = xpdf_page(pidx + 1)
    cache = {}
    # componente pela aba lateral (texto vertical à direita)
    side = " ".join(norm_ws(fix_text(l["text"], page_text, cache)) for l in lines if l["vertical"] and l["x0"] > W - 70)
    comp = None
    for key, name, abbr in SIDE_COMPONENTS:
        if key in plain(side):
            comp = (name, abbr)
            break
    if comp is None:
        stats["pages_skipped"] += 1
        stats.setdefault("no_component", []).append(pidx + 1)
        continue
    if comp[1] == "AR":
        for lang in ("ARTES VISUAIS", "TEATRO", "DANCA", "MUSICA"):
            if lang in plain(side):
                arte_lang = {"ARTES VISUAIS": "Artes Visuais", "TEATRO": "Teatro", "DANCA": "Dança",
                             "MUSICA": "Música"}[lang]
    lang = arte_lang if comp[1] == "AR" else ""
    head_y = max(h["y1"] for h in heads)
    cols = sorted(((h["x0"] + h["x1"]) / 2, "obj" if norm_ws(h["text"]).startswith("OBJ") else "cont") for h in heads)
    ycent = [((y["x0"] + y["x1"]) / 2, int(re.match(r"\d", norm_ws(y["text"])).group(0))) for y in years]
    bounds = []
    for i, (cx, role) in enumerate(cols):
        left = (cols[i - 1][0] + cx) / 2 if i else 0
        right = (cx + cols[i + 1][0]) / 2 if i + 1 < len(cols) else W - 60
        year = min(ycent, key=lambda yc: abs(yc[0] - cx))[1]
        bounds.append((left, right, role, year))
    body = [l for l in lines if l["y0"] > head_y + 1 and not l["vertical"] and l["y0"] < page.rect.height - 45]
    for left, right, role, year in bounds:
        col = sorted((l for l in body if left <= (l["x0"] + 2) < right), key=lambda l: (round(l["y0"]), l["x0"]))
        key = (comp[1], lang, year, role)
        cur = state.get(key)
        units = unit_state.setdefault(key, {"unit": "", "sub": ""})
        seen = obj_units.setdefault((comp[1], lang, year), set())
        # 1ª passada: junta títulos em negrito de várias linhas num só
        tokens = []
        for l in col:
            t = fix_text(l["text"], page_text, cache)
            if not t:
                continue
            if l["bold"] and not l["bullet"]:
                if (tokens and tokens[-1][0] == "head" and l["y0"] - tokens[-1][2] < 16
                        and not (role == "cont" and plain(tokens[-1][1]) in seen)):
                    tokens[-1] = ("head", tokens[-1][1] + " " + t, l["y1"], None)
                else:
                    tokens.append(("head", t, l["y1"], None))
            else:
                tokens.append(("bullet" if l["bullet"] else "line", t, l["y1"], l))
        for kind, t, _y, l in tokens:
            if kind == "head":
                # eixo/unidade; na coluna de conteúdos, título que não é eixo dos objetivos é subtítulo
                if role == "obj":
                    units["unit"], units["sub"] = t, ""
                    seen.add(plain(t))
                elif plain(t) in seen:
                    units["unit"], units["sub"] = t, ""
                else:
                    units["sub"] = t
                cur = None
                continue
            if kind == "bullet":
                cur = {"component": comp[0], "abbr": comp[1], "lang": lang, "year": year, "role": role,
                       "unit": units["unit"], "sub": units["sub"] if role == "cont" else "", "text": t,
                       "page": pidx + 1, "x": l["x0"]}
                items.append(cur)
            elif cur is not None:
                cur["text"] += " " + t
            else:
                # linha solta sem marcador nem item anterior: guarda para revisão
                items.append({"component": comp[0], "abbr": comp[1], "lang": lang, "year": year, "role": role,
                              "unit": units["unit"], "sub": units["sub"] if role == "cont" else "", "text": t,
                              "page": pidx + 1, "x": l["x0"], "orphan": True})
                cur = items[-1]
        state[key] = cur
        # títulos de unidade continuam valendo na página seguinte

# mesma unidade escrita com maiúsculas diferentes ("Grandezas e medidas"): usa a forma mais frequente
from collections import Counter
forms = Counter((it["abbr"], it["unit"]) for it in items if it["unit"])
best = {}
for (abbr, u), n in forms.most_common():
    best.setdefault((abbr, u.lower()), u)
for it in items:
    if it["unit"]:
        it["unit"] = best[(it["abbr"], it["unit"].lower())]
    # quebra de linha logo depois do hífen ("situações- problema" → "situações-problema")
    it["text"] = re.sub(r"(\w)- (\w)", r"\1-\2", norm_ws(it["text"]))
    if FFFD in it["text"] or FFFD in it["unit"]:
        stats["fffd_left"] += 1

json.dump({"stats": stats, "items": items}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
print(json.dumps(stats, ensure_ascii=False)[:600], len(items))
