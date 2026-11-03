"""Currículo em Movimento do DF (Ensino Fundamental, 2ª ed., 2018) incluído na plataforma.

O arquivo `data/curriculo_em_movimento_df_ef.json` foi extraído automaticamente das
tabelas do PDF (scripts em `data/extracao/curriculo_df_*.py`). O documento não tem
códigos oficiais: os códigos CMDF-* são identificadores locais. Por isso cada item
entra com "texto a conferir" e cada ligação com a BNCC é só uma sugestão automática,
de confiança baixa, até a coordenação validar.
"""

import json
import math
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from django.db import transaction

from apps.core.fmt import dec

from .models import CurriculumCorrespondence, CurriculumItem

DATA = Path(__file__).resolve().parent / "data" / "curriculo_em_movimento_df_ef.json"
# Calibrado lendo amostras na cópia do banco (31/10/2026): abaixo de 0,3 as sugestões quase sempre
# erravam; acima de 0,7 o objetivo repete o texto da habilidade.
MIN_SCORE = 0.3
SAME_TEXT = 0.7
PER_ITEM = 2


@lru_cache(maxsize=1)
def dataset():
    return json.loads(DATA.read_text(encoding="utf-8"))


def imported_count(school):
    return CurriculumItem.objects.filter(school=school, code__startswith="CMDF-").count()


def _tokens(text):
    from apps.cognitio.nlp import STOP, plain, stem, words

    return [stem(w) for w in words(text) if plain(w) not in STOP and len(w) > 3]


def _suggest(objectives, school):
    """Para cada objetivo, as habilidades da BNCC do mesmo componente e ano com mais palavras em comum
    (TF-IDF e cosseno). Devolve [(objetivo, habilidade, nota, palavras)]."""
    groups = defaultdict(list)
    for it in objectives:
        groups[(it.component, int(it.years))].append(it)
    out = []
    for (comp, year), objs in groups.items():
        skills = [s for s in CurriculumItem.for_pair(school, comp, year) if s.kind == CurriculumItem.Kind.SKILL]
        if not skills:
            continue
        docs = {s.pk: _tokens(f"{s.text} {s.knowledge_object}") for s in skills}
        df = Counter(w for ws in docs.values() for w in set(ws))
        idf = {w: math.log((len(docs) + 1) / (n + 1)) + 1 for w, n in df.items()}

        def vec(ws):
            c = Counter(ws)
            total = sum(c.values()) or 1
            v = {w: n / total * idf.get(w, 0) for w, n in c.items()}
            return v, math.sqrt(sum(x * x for x in v.values())) or 1

        svecs = {s.pk: vec(docs[s.pk]) for s in skills}
        for o in objs:
            q, qn = vec(_tokens(o.text))
            scored = []
            for s in skills:
                d, dn = svecs[s.pk]
                score = sum(q[w] * d.get(w, 0) for w in q) / (qn * dn)
                if score >= MIN_SCORE:
                    shared = sorted(set(q) & set(d), key=lambda w: -q[w] * d[w])[:4]
                    scored.append((score, s, shared))
            scored.sort(key=lambda r: -r[0])
            out += [(o, s, score, shared) for score, s, shared in scored[:PER_ITEM]]
    return out


def import_for_school(school, user):
    """Cria os itens que faltam e atualiza só os que ainda estão "a conferir".

    Item já conferido pela escola (texto revisado) não é sobrescrito. Correspondência
    já validada ou rejeitada também não é tocada.
    """
    data = dataset()
    meta = data["meta"]
    existing = {i.code: i for i in CurriculumItem.objects.filter(school=school, code__startswith="CMDF-")}
    created = updated = kept = 0
    touched = []
    with transaction.atomic():
        for row in data["itens"]:
            fields = {
                "text": row["texto"], "component": row["componente"], "years": str(row["ano"]),
                "thematic_unit": row["unidade"][:160], "knowledge_object": row["subtitulo"],
                "stage": "Ensino Fundamental", "curriculum_version": "Currículo em Movimento do DF, 2ª ed. (2018)",
                "source": f"{meta['titulo']}, {meta['edicao']}, SEEDF, {meta['ano']}, p. {row['pagina_pdf']} do PDF"[:250],
                "source_url": meta["copia_usada"], "structure_auto": True, "active": True,
            }
            item = existing.get(row["codigo"])
            if item is None:
                item = CurriculumItem.objects.create(school=school, kind=row["tipo"], code=row["codigo"],
                                                     needs_review=True, created_by=user, **fields)
                created += 1
            elif item.needs_review:
                for k, v in fields.items():
                    setattr(item, k, v)
                item.save()
                updated += 1
            else:
                kept += 1
            if item.kind == CurriculumItem.Kind.DF_OBJECTIVE:
                touched.append(item)
        decided = set(CurriculumCorrespondence.objects.filter(school=school, source__in=touched)
                      .filter(validated=True).values_list("source_id", "target_id"))
        decided |= set(CurriculumCorrespondence.objects.filter(school=school, source__in=touched, rejected=True)
                       .values_list("source_id", "target_id"))
        suggestions = 0
        for o, s, score, shared in _suggest(touched, school):
            if (o.pk, s.pk) in decided:
                continue
            CurriculumCorrespondence.objects.update_or_create(school=school, source=o, target=s, defaults={
                "relation": CurriculumCorrespondence.Relation.RELATED,
                "confidence": (CurriculumCorrespondence.Confidence.MEDIUM if score >= SAME_TEXT
                               else CurriculumCorrespondence.Confidence.LOW),
                "origin": CurriculumCorrespondence.Origin.AUTO,
                "rationale": (f"{'Texto quase igual ao da habilidade. ' if score >= SAME_TEXT else ''}"
                              f"Semelhança de palavras {dec(score)} (raízes em comum: {', '.join(shared)})")[:300],
            })
            suggestions += 1
    return {"created": created, "updated": updated, "kept": kept, "suggestions": suggestions}
