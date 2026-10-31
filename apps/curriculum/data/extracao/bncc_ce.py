"""Competências específicas (por área e por componente) do Ensino Fundamental, do texto oficial da BNCC."""
import json
import re
import sys

src_txt, src_json, out = sys.argv[1:4]
lines = open(src_txt, encoding="utf-8").read().split("\n")
data = json.load(open(src_json, encoding="utf-8"))

TARGETS = [
    ("LINGUAGENS PARA O", "area", "Linguagens"),
    ("LÍNGUA PORTUGUESA", "componente", "Língua Portuguesa"),
    ("ARTE PARA O ENSINO", "componente", "Arte"),
    ("EDUCAÇÃO FÍSICA PARA O", "componente", "Educação Física"),
    ("LÍNGUA INGLESA PARA O", "componente", "Língua Inglesa"),
    ("MATEMÁTICA PARA O", "componente", "Matemática"),
    ("CIÊNCIAS DA NATUREZA", "componente", "Ciências"),
    ("CIÊNCIAS HUMANAS PARA", "area", "Ciências Humanas"),
    ("GEOGRAFIA PARA O", "componente", "Geografia"),
    ("HISTÓRIA PARA O", "componente", "História"),
    ("ENSINO RELIGIOSO PARA", "componente", "Ensino Religioso"),
]
SKIP = re.compile(r"^(=====PAGE|\d+\s*$|BASE NACIONAL|COMUM CURRICULAR|ENSINO FUNDAMENTAL\s*$|"
                  r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ ]+\s*$)")
out_ce = []
used = set()
for i, line in enumerate(lines):
    if not line.startswith("COMPETÊNCIAS ESPECÍFICAS DE"):
        continue
    for key, level, name in TARGETS:
        if key in line and name not in used:
            break
    else:
        continue
    used.add(name)
    items, cur, expected = [], None, 1
    for raw in lines[i + 1:i + 160]:
        t = raw.strip()
        if not t or SKIP.match(t):
            continue
        m = re.match(r"^(\d{1,2})\.\s+(.*)$", t)
        if m and int(m.group(1)) == expected:
            if cur:
                items.append(cur)
            cur, expected = m.group(2), expected + 1
            continue
        if cur is None:
            continue
        if cur.endswith(".") and not t[0].islower():
            break  # fim da lista
        cur = cur[:-1] + t if cur.endswith("-") else cur + " " + t
    if cur:
        items.append(cur)
    for n, txt in enumerate(items, 1):
        out_ce.append({"level": level, "name": name, "n": n, "text": re.split(r"(?<=\.) (?=[a-zà-ú])", re.sub(r"\s+", " ", txt).strip())[0]})
data["competencias_especificas"] = out_ce
for h in data["habilidades"]:
    if h.get("unit") == "Formas de representação e pensamento" and h.get("object", "").startswith("espacial"):
        h["unit"] = "Formas de representação e pensamento espacial"
        h["object"] = h["object"][len("espacial"):].strip()
json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
from collections import Counter
print(Counter(c["name"] for c in out_ce))
