"""Unidade temática e objeto de conhecimento pela posição na página dupla da BNCC.

Nas tabelas do PDF oficial, a página da esquerda tem UNIDADES TEMÁTICAS (negrito) e OBJETOS DE
CONHECIMENTO; a da direita tem as HABILIDADES, na mesma altura. Unidade e objeto ficam no topo da
linha da tabela: a habilidade pertence ao último bloco que começa acima (ou na altura) do seu código.

Uso: python -I bncc_units_pos.py <bncc.pdf> <bncc_ensino_fundamental.json> <saida.json>
"""
import json
import re
import sys

import fitz

SRC, DATA, OUT = sys.argv[1:4]
CODE = re.compile(r"^\((EF\d{2}[A-Z]{2}\d{2})\)")


def lines(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            spans = [s for s in l["spans"] if s["text"].strip()]
            if spans:
                out.append({"x0": l["bbox"][0], "y0": l["bbox"][1], "y1": l["bbox"][3],
                            "text": "".join(s["text"] for s in spans).strip(),
                            "bold": "Bold" in spans[0]["font"], "font": spans[0]["font"]})
    return out


def blocks(ls, gap=16):
    """Junta linhas seguidas (mesma coluna) num bloco: [(y_inicio, texto)]."""
    out = []
    for l in sorted(ls, key=lambda l: l["y0"]):
        if out and l["y0"] - out[-1][2] < gap - 10:
            out[-1][1].append(l["text"])
            out[-1][2] = l["y1"]
        else:
            out.append([l["y0"], [l["text"]], l["y1"]])
    return [(y, re.sub(r"(\w)- (\w)", r"\1\2", " ".join(t))) for y, t, _ in out]


doc = fitz.open(SRC)
found = {}
carry_unit = carry_obj = ""
for pno in range(1, doc.page_count):
    right = lines(doc[pno])
    if not any(l["text"] == "HABILIDADES" for l in right):
        continue
    left = lines(doc[pno - 1])
    head = next((l for l in left if l["text"] in ("UNIDADES TEMÁTICAS", "PRÁTICAS DE LINGUAGEM")), None)
    objh = next((l for l in left if l["text"] == "OBJETOS DE CONHECIMENTO"), None)
    if head is None or objh is None:
        continue
    body = [l for l in left if l["y0"] > objh["y1"] and l["y0"] < 790]
    units = blocks([l for l in body if l["x0"] < objh["x0"] - 5 and l["bold"]])
    objs = blocks([l for l in body if l["x0"] >= objh["x0"] - 5])
    # linhas separadoras da tabela (traços horizontais nas duas páginas): a célula de objetos vale para
    # todas as habilidades da mesma linha, então os objetos são agrupados por linha, não por altura
    seps = sorted({round(dr["rect"].y0) for pg in (doc[pno - 1], doc[pno]) for dr in pg.get_drawings()
                   if dr["rect"].height < 1.5 and dr["rect"].width > 150 and dr["rect"].y0 > objh["y1"] - 4})
    for l in sorted(right, key=lambda l: l["y0"]):
        m = CODE.match(l["text"])
        if not m:
            continue
        y = l["y0"] + 3
        top = max([s for s in seps if s <= y], default=objh["y1"])
        bottom = min([s for s in seps if s > y], default=800)
        u = [t for (yy, t) in units if yy <= y]
        o = [t for (yy, t) in objs if top - 3 <= yy < bottom - 3]
        unit = u[-1] if u else carry_unit
        obj = " ".join(o) if o else carry_obj
        found.setdefault(m.group(1), {"unit": unit, "object": obj, "page": pno + 1, "row": [top, bottom]})
    if units:
        carry_unit = units[-1][1]
    if objs:
        carry_obj = objs[-1][1]

data = json.load(open(DATA, encoding="utf-8"))
json.dump(found, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
from collections import Counter
print("lidas:", len(found), "de", len(data["habilidades"]))
diff_u = [(h["component"], h["code"], h.get("unit", ""), found[h["code"]]["unit"]) for h in data["habilidades"]
          if h["code"] in found and found[h["code"]]["unit"] != h.get("unit", "")]
print("unidades diferentes:", len(diff_u), Counter(d[0] for d in diff_u))
missing = [h["code"] for h in data["habilidades"] if h["code"] not in found]
print("não lidas:", len(missing), Counter(c[4:6] for c in missing))
for d in diff_u:
    print(f"  {d[1]}: {d[2]!r} -> {d[3]!r}")
