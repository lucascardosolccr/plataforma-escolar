"""Aplica ao arquivo da BNCC as unidades e objetos lidos por posição (bncc_units_pos.py).

Uso: python bncc_units_aplicar.py <bncc_ensino_fundamental.json> <units_pos.json>

Regras (conferidas em 31/10/2026, ver EIA_COGNITIO_ONTOLOGIA_CURRICULAR.md):
- unidade: aplicada em todos os componentes quando a leitura nova não é vazia nem nota de rodapé ("*...");
  em Língua Portuguesa só quando a nova completa a antiga ("Análise linguística/semiótica" →
  "... (Alfabetização)"), quando a antiga era fragmento de nota ou quando o 1º/2º ano usa
  "Escrita (compartilhada e autônoma)";
- objeto de conhecimento: aplicado só em História e Língua Inglesa, onde o extrator antigo misturava
  pedaços da unidade no começo do objeto. Objetos da mesma linha da tabela ficam juntos.
O texto das habilidades nunca é alterado.
"""
import json
import sys

DATA, POS = sys.argv[1:3]
data = json.load(open(DATA, encoding="utf-8"))
pos = json.load(open(POS, encoding="utf-8"))
LP_FRAGMENT = "ou produções orais, em áudio ou vídeo"
units = objects = 0
for h in data["habilidades"]:
    p = pos.get(h["code"])
    if not p:
        continue
    old, new = h.get("unit", ""), p["unit"]
    if h["code"] == "EF69LP11":
        new = "Oralidade"  # a leitura pegou a nota de rodapé da mesma linha
    ok = bool(new) and not new.startswith("*") and new != old
    if ok and h["component"] == "Língua Portuguesa":
        ok = (new.startswith(old + " (") or old == LP_FRAGMENT
              or (old == "Produção de textos" and new == "Escrita (compartilhada e autônoma)"))
    if ok:
        h["unit"] = new
        units += 1
    if h["component"] in ("História", "Língua Inglesa") and p["object"] and p["object"] != h.get("object", ""):
        h["object"] = p["object"]
        objects += 1
with open(DATA, "w", encoding="utf-8", newline="\n") as f:
    json.dump(data, f, ensure_ascii=False, indent=0)
print(f"unidades corrigidas: {units}; objetos corrigidos: {objects}")
