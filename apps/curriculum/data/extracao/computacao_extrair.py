"""Extrai as habilidades do Ensino Fundamental do complemento de Computação à BNCC.

Fonte: Anexo ao Parecer CNE/CEB nº 2/2022 (Computação na Educação Básica — Complemento à BNCC),
PDF do site oficial da BNCC (basenacionalcomum.mec.gov.br).

Uso: python -I co_extract.py <anexo.pdf> <saida.json> <sha256>

As tabelas têm linhas desenhadas: o PyMuPDF acha as células (célula mesclada = None, herda a de
cima, inclusive da página anterior) e o texto de cada célula é lido pelo retângulo dela.
"""
import json
import re
import sys

import fitz

SRC, OUT, SHA = sys.argv[1:4]
CODE = re.compile(r"\((EF(\d)(\d)CO(\d\d))\)\s*")
EIXOS = {"PENSAMENTOCOMPUTACIONAL": "Pensamento computacional", "MUNDODIGITAL": "Mundo digital",
         "CULTURADIGITAL": "Cultura digital"}


def clean(t):
    t = re.sub(r"\s+", " ", t or "").strip()
    return re.sub(r"(\w)- (\w)", r"\1-\2", t)


doc = fitz.open(SRC)
skills, carry = [], None
for pno in range(doc.page_count):
    page = doc[pno]
    if "HABILIDADE" not in page.get_text() or not CODE.search(page.get_text()):
        continue
    for t in page.find_tables().tables:
        ncol = t.col_count
        for r_idx, row in enumerate(t.rows):
            cells = row.cells
            texts = [clean(page.get_text("text", clip=fitz.Rect(c))) if c else None for c in cells]
            if texts and texts[0] == "EIXO":
                continue
            # célula mesclada herda o valor da linha de cima
            if carry is None or len(carry) != ncol:
                carry = [""] * ncol
            vals = [texts[i] if texts[i] is not None else carry[i] for i in range(ncol)]
            carry = vals
            hab = next((v for v in reversed(texts) if v and CODE.search(v)), None)
            if not hab:
                continue
            for part in re.split(r"(?=\(EF\d\dCO\d\d\))", hab):
                m = CODE.match(part)
                if not m:
                    continue
                code, d1, d2 = m.group(1), int(m.group(2)), int(m.group(3))
                years = [d2] if d1 == 0 else list(range(d1, d2 + 1))
                eixo_raw = re.sub(r"\s+", "", vals[0]).upper()
                eixo = next((v for k, v in EIXOS.items() if k in eixo_raw), "")
                if ncol == 3:
                    obj = vals[1]
                else:
                    obj = ": ".join(v for v in (vals[1], vals[2]) if v)
                skills.append({"code": code, "text": clean(part[m.end():]), "years": years, "eixo": eixo,
                               "objeto": obj, "page": pno + 1})

codes = [s["code"] for s in skills]
assert len(codes) == len(set(codes)), [c for c in codes if codes.count(c) > 1]
meta = {
    "titulo": "Computação na Educação Básica — Complemento à BNCC (Anexo ao Parecer CNE/CEB nº 2/2022)",
    "norma": "Parecer CNE/CEB nº 2/2022 (homologado em 17/02/2022) e Resolução CNE/CEB nº 1/2022 (4/10/2022)",
    "fonte": "https://basenacionalcomum.mec.gov.br/images/historico/anexo_parecer_cneceb_n_2_2022_bncc_computacao.pdf",
    "sha256_pdf": SHA, "extraido_em": "2026-10-31", "total": len(skills),
}
json.dump({"meta": meta, "habilidades": skills}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(skills), sorted({s["eixo"] for s in skills}), sum(1 for s in skills if not s["objeto"]))
