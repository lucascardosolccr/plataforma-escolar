"""Converte cm_items.json no arquivo de dados da plataforma, com códigos locais estáveis."""
import json
import sys
from collections import Counter, defaultdict

src, out, sha = sys.argv[1], sys.argv[2], sys.argv[3]
items = json.load(open(src, encoding="utf-8"))["items"]
LANG = {"Artes Visuais": "AV", "Teatro": "TE", "Dança": "DA", "Música": "MU"}
seq = defaultdict(int)
rows = []
for it in items:
    abbr = it["abbr"] + LANG.get(it["lang"], "")
    role = "O" if it["role"] == "obj" else "C"
    key = (abbr, it["year"], role)
    seq[key] += 1
    unit = f'{it["lang"]} · {it["unit"]}' if it["lang"] and it["unit"] else (it["lang"] or it["unit"])
    rows.append({
        "codigo": f"CMDF-{abbr}{it['year']:02d}-{role}{seq[key]:03d}",
        "tipo": "objetivo_df" if role == "O" else "conteudo_df",
        "componente": it["component"], "ano": it["year"], "unidade": unit, "subtitulo": it["sub"],
        "texto": it["text"], "pagina_pdf": it["page"],
    })
codes = [r["codigo"] for r in rows]
assert len(codes) == len(set(codes))
counts = Counter((r["componente"], r["tipo"]) for r in rows)
meta = {
    "titulo": "Currículo em Movimento do Distrito Federal – Ensino Fundamental: Anos Iniciais – Anos Finais",
    "edicao": "2ª edição", "ano": 2018, "editor": "Secretaria de Estado de Educação do Distrito Federal (SEEDF)",
    "portal_oficial": "https://www.educacao.df.gov.br/curriculo-em-movimento/",
    "copia_usada": "https://observatoriodeeducacao.institutounibanco.org.br/api/assets/1ecafdbd-fb04-4814-950e-025064476e91",
    "sha256_pdf": sha, "paginas_pdf": 312, "extraido_em": "2026-10-31",
    "metodo": "Extração automática das tabelas (posição e negrito pelo PyMuPDF; texto com acentos pelo pdftotext). "
              "O documento não tem códigos oficiais: os códigos CMDF-* são identificadores locais da plataforma.",
    "aviso": "Texto a conferir com o documento oficial da SEEDF. O portal da SEEDF recusou conexão por certificado "
             "inválido; a cópia usada está hospedada no Observatório de Educação do Instituto Unibanco.",
    "totais": {f"{c} / {t}": n for (c, t), n in sorted(counts.items())},
}
with open(out, "w", encoding="utf-8", newline="\n") as f:
    f.write('{"meta": ' + json.dumps(meta, ensure_ascii=False, indent=1) + ',\n"itens": [\n')
    f.write(",\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    f.write("\n]}\n")
print(len(rows), "itens")
