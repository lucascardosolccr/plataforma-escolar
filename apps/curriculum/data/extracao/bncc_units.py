"""Acrescenta unidade temática (ou prática de linguagem) e objeto de conhecimento às habilidades.

Heurística sobre o texto do PDF oficial da BNCC: nas tabelas, a unidade temática aparece
com tabulações entre as palavras (ou é um nome de unidade da BNCC no começo da linha), e
o objeto de conhecimento é o texto antes do código ou entre uma habilidade e a próxima.
O resultado é marcado como extração automática (conferir).
"""
import json
import re
import sys

src_txt, src_json, out = sys.argv[1:4]
text = open(src_txt, encoding="utf-8").read()
# O PDF separa o "T" maiúsculo da letra seguinte ("T erra", "T eatro").
text = re.sub(r"\bT ([a-zçãéêíóú])", r"T\1", text)
data = json.load(open(src_json, encoding="utf-8"))

UNITS = {
    "MA": ["Números", "Álgebra", "Geometria", "Grandezas e medidas", "Probabilidade e estatística"],
    "CI": ["Matéria e energia", "Vida e evolução", "Terra e Universo"],
    "GE": ["O sujeito e seu lugar no mundo", "Conexões e escalas", "Mundo do trabalho",
           "Formas de representação e pensamento espacial", "Natureza, ambientes e qualidade de vida"],
    "AR": ["Artes visuais", "Dança", "Música", "Teatro", "Artes integradas"],
    "EF": ["Brincadeiras e jogos", "Esportes", "Ginásticas", "Danças", "Lutas", "Práticas corporais de aventura"],
    "ER": ["Identidades e alteridades", "Manifestações religiosas", "Crenças religiosas e filosofias de vida"],
    "LI": ["Oralidade", "Leitura", "Escrita", "Conhecimentos linguísticos", "Dimensão intercultural"],
    "LP": ["Leitura/escuta", "Produção de textos", "Escrita", "Oralidade", "Análise linguística/semiótica",
           "Leitura"],
}
CODE = re.compile(r"\((EF\d{2}([A-Z]{2})\d{2})\)")
HEADER = re.compile(r"^(BASE NACIONAL|COMUM CURRICULAR|\d+\s*$|UNIDADES TEMÁTICAS|PRÁTICAS DE LINGUAGEM|EIXO|"
                    r"=====PAGE|\d+º\s?ANO|CAMPO|TODOS OS CAMPOS|HABILIDADES|LÍNGUA |MATEMÁTICA|CIÊNCIAS|"
                    r"GEOGRAFIA|HISTÓRIA|ARTE|EDUCAÇÃO FÍSICA|ENSINO RELIGIOSO|LÍNGUA INGLESA)")
TABBED = re.compile(r"^((?:[^\s\t]+\t)+[^\s\t]*)\s*(.*)$")


def norm(s):
    return re.sub(r"\s+", " ", s.replace("\t", " ")).strip()


def known_unit(t, comp):
    for u in sorted(UNITS.get(comp, []), key=len, reverse=True):
        if t.startswith(u):
            rest = t[len(u):].strip()
            if not rest or rest[0].isupper() or rest[0] == "(":
                return u, rest
    return None, t


unit, result = {}, {}
obj, obj_open, in_skill, comp, in_table = "", False, False, None, False
TABLE_HEAD = re.compile(r"(UNIDADES? TEMÁTICAS?|PRÁTICAS DE LINGUAGEM|OBJETOS DE CONHECIMENTO)")


def read_unit(line, comp):
    """Devolve (unidade ou None, resto)."""
    s = line.strip()
    m = TABBED.match(s)
    if m:
        head = norm(m.group(1))
        if head.startswith("("):
            return (unit.get(comp, "") + " " + head).strip(), norm(m.group(2))
        u, rest = known_unit(norm(s), comp)
        if u:
            return u, rest
        return head, norm(m.group(2))
    return known_unit(norm(s), comp)


for raw in text.split("\n"):
    line = raw.rstrip()
    if not line.strip():
        continue
    if line.startswith("=====PAGE"):
        in_table, obj_open, in_skill = False, False, False
        continue
    if TABLE_HEAD.search(line) and not CODE.search(line):
        in_table = True
        continue
    if HEADER.match(norm(line)) and not CODE.search(line):
        continue
    m = CODE.search(line)
    if m:
        code, comp = m.group(1), m.group(2)
        prefix = line[:m.start()] if in_table else ""
        if not in_table and not obj_open:
            pass
        if prefix.strip():
            u, rest = read_unit(prefix, comp)
            if u:
                unit[comp] = u
                piece = rest
            else:
                piece = norm(prefix)
            if piece:
                obj = (obj + " " + piece).strip() if obj_open else piece
        result.setdefault(code, {"unit": unit.get(comp, ""), "object": obj})
        obj_open = False
        in_skill = not line.endswith(".")
        continue
    if in_skill:
        if line.endswith("."):
            in_skill = False
        continue
    if comp is None or not in_table:
        continue
    u, rest = read_unit(line, comp)
    if u:
        unit[comp] = u
        obj, obj_open = rest, bool(rest)
        continue
    t = norm(line)
    obj = (obj + " " + t).strip() if obj_open else t
    obj_open = True

for h in data["habilidades"]:
    info = result.get(h["code"], {})
    h["unit"] = info.get("unit", "")[:120]
    h["object"] = info.get("object", "")[:400]
json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
have_u = sum(1 for h in data["habilidades"] if h["unit"])
have_o = sum(1 for h in data["habilidades"] if h["object"])
print(len(data["habilidades"]), "com unidade:", have_u, "com objeto:", have_o)
