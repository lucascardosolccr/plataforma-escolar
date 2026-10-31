"""Extrai competências gerais e habilidades do Ensino Fundamental do texto da BNCC (PDF oficial do MEC)."""
import json
import re
import sys
from collections import Counter

src, out = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()
# Remove cabeçalhos de página.
text = re.sub(r"\n=====PAGE \d+=====\n", "\n", text)
lines = [l.rstrip() for l in text.split("\n")]
VOCAB = set(re.findall(r"\w+", text.lower()))

CODE = re.compile(r"\((EF\d{2}[A-Z]{2}\d{2})\)\s*(.*)")
COMP = {"LP": "Língua Portuguesa", "MA": "Matemática", "CI": "Ciências", "GE": "Geografia", "HI": "História",
        "AR": "Arte", "EF": "Educação Física", "LI": "Língua Inglesa", "ER": "Ensino Religioso"}
found = {}
variants = Counter()
i = 0
while i < len(lines):
    m = CODE.search(lines[i])
    if not m:
        i += 1
        continue
    code, rest = m.group(1), m.group(2).strip()
    parts = [rest]
    j = i + 1
    # junta linhas até a frase terminar em ponto (as habilidades terminam em ".")
    while not "".join(parts).rstrip().endswith(".") and j < len(lines) and j < i + 30:
        nxt = lines[j].strip()
        if CODE.search(nxt) or not nxt:
            break
        parts.append(nxt)
        j += 1
    body = ""
    for p in parts:
        frag = re.search(r"(\w+)-$", body)
        first = re.match(r"\w+", p)
        if frag and first and (frag.group(1) + first.group(0)).lower() in VOCAB:
            body = body[:-1] + p  # hifenização de fim de linha
        elif body.endswith("-"):
            body = body + p  # hífen de palavra composta (matérias-primas)
        else:
            body = (body + " " + p).strip()
    body = re.sub(r"\s+", " ", body).strip()
    if len(body) > 20:
        complete = body.endswith(".")
        if complete:
            variants[(code, body)] += 1
        prev = found.get(code)
        if prev is None or (complete and (not prev[1] or len(body) > len(prev[0]))):
            found[code] = (body, complete)
    i = j if j > i else i + 1


def years(code):
    a, b = int(code[2]), int(code[3])
    return [b] if a == 0 else list(range(a, b + 1))


items = []
for code in sorted(found):
    comp = code[4:6]
    if comp not in COMP:
        continue
    items.append({"code": code, "component": COMP[comp], "years": ",".join(str(y) for y in years(code)),
                  "text": found[code][0], "review": not found[code][1]})

# Competências gerais (texto corrido, dividido por página)
start = text.index("COMPETÊNCIAS GERAIS DA EDUCAÇÃO BÁSICA")
chunk = text[start:start + 9000]
gen = {}
for n in range(1, 11):
    m = re.search(rf"\n{n}\. (.+?)(?=\n{n + 1}\. |\nBASE NACIONAL|\nOs marcos legais|\Z)", chunk, re.S)
    if m:
        t = re.sub(r"-\n", "", m.group(1))
        t = re.sub(r"\s+", " ", t).strip()
        gen[n] = t[: t.index(".") + 1]
json.dump({"habilidades": items, "competencias_gerais": gen}, open(out, "w", encoding="utf-8"),
          ensure_ascii=False, indent=0)
print(len(items), "habilidades;", len(gen), "competências")
print(Counter(i["component"] for i in items))
conflicts = Counter(c for (c, _b) in variants)
print("códigos com mais de uma redação:", sum(1 for c, n in conflicts.items() if n > 1))
