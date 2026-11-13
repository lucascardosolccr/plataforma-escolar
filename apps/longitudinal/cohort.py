"""Análises da escola ao longo dos anos, a partir das linhas do tempo dos estudantes.

- **Taxas de rendimento** por ano: aprovação, retenção e abandono sobre quem terminou o ano na escola (como as
  taxas de rendimento do Censo Escolar, que excluem os transferidos), com a parte do resultado que é oficial.
- **Distorção idade-série** por etapa no ano atual (definição do INEP), com IC de Wilson.
- **Matriz de transição** entre faixas de desempenho de um ano para o seguinte: quanto a posição de um ano se
  mantém no outro.
- **Validação local dos sinais:** para cada sinal do diagnóstico, a frequência de desfecho desfavorável no ano
  seguinte com e sem o sinal, com risco relativo e IC 95%. Um sinal que funciona na literatura precisa funcionar
  também na escola (Bowers, Sprott & Taff, 2013, The High School Journal 96(2), 77–100).
- **Estabilidade das médias** entre anos seguidos (Spearman): o quanto o ano passado diz sobre este.

Regra do BI mantida: grupo com menos de 5 estudantes não aparece (``MIN_GROUP``), e ausência de dado nunca é zero.
"""

from collections import Counter, defaultdict

from . import stats
from .models import Outcome
from .timeline import adverse

MIN_GROUP = 5
BANDS = [("abaixo", "Abaixo da média"), ("adequado", "Da média a 7,9"), ("avancado", "8 ou mais")]


def band(row):
    if row["average"] is None:
        return None
    passing = min((s["passing"] for s in row["subjects"] if s.get("passing") is not None), default=6.0)
    if row["average"] < passing:
        return "abaixo"
    return "avancado" if row["average"] >= 8 else "adequado"


def flow_rates(timelines):
    by_year = defaultdict(Counter)
    for rows in timelines.values():
        for r in rows:
            if r["in_progress"]:
                continue
            by_year[r["year"]]["total"] += 1
            if r["basis"] == "oficial":
                by_year[r["year"]]["oficial"] += 1
            if r["promoted"]:
                by_year[r["year"]]["aprovado"] += 1
            elif r["retained"]:
                by_year[r["year"]]["retido"] += 1
            elif r["outcome"] == Outcome.DROPOUT:
                by_year[r["year"]]["abandono"] += 1
            elif r["outcome"] == Outcome.TRANSFERRED:
                by_year[r["year"]]["transferido"] += 1
            else:
                by_year[r["year"]]["indefinido"] += 1
    out = []
    for year in sorted(by_year):
        c = by_year[year]
        base = c["aprovado"] + c["retido"] + c["abandono"]
        row = {"year": year, "total": c["total"], "base": base, "official": c["oficial"],
               "transferred": c["transferido"], "undefined": c["indefinido"], "hidden": base < MIN_GROUP}
        for k in ("aprovado", "retido", "abandono"):
            row[k] = None if row["hidden"] else 100.0 * c[k] / base
        out.append(row)
    return out


def survival_curve(timelines):
    """Curva de retenção de Kaplan–Meier: a probabilidade de o estudante ainda estar na escola a cada
    ano de permanência, tratando o abandono como evento e quem segue, transfere ou conclui como censura.

    O tempo é o ano de permanência (1º, 2º, ...), não o ano letivo, então coortes diferentes entram na
    mesma curva. Complementa as taxas de rendimento (que são por ano letivo): mostra onde, ao longo da
    vida escolar, o risco de abandono se concentra. Grupo com menos de ``MIN_GROUP`` fica de fora.
    """
    obs = []
    for rows in timelines.values():
        t, event = 0, False
        for r in rows:
            t += 1
            if r["outcome"] == Outcome.DROPOUT:
                event = True
                break
            if r["outcome"] == Outcome.TRANSFERRED or r["in_progress"]:
                break  # censura: saiu sem abandono, ou ainda está na escola neste ano
        if t:
            obs.append((t, event))
    if len(obs) < MIN_GROUP:
        return None
    res = stats.kaplan_meier(obs)
    if res:
        for st in res["steps"]:  # versão em porcentagem para a tabela
            st["pct"], st["pct_low"], st["pct_high"] = 100 * st["survival"], 100 * st["low"], 100 * st["high"]
    return res


def distortion_by_stage(timelines):
    groups = defaultdict(lambda: [0, 0, 0])  # etapa -> [com idade, em distorção, sem data de nascimento]
    labels = {}
    for rows in timelines.values():
        cur = next((r for r in reversed(rows) if r["in_progress"]), None)
        if not cur or not cur["stage"]:
            continue
        labels[cur["stage"]] = cur["stage_label"]
        if cur["distortion"] is None:
            groups[cur["stage"]][2] += 1
            continue
        groups[cur["stage"]][0] += 1
        groups[cur["stage"]][1] += int(cur["distortion"] >= 2)
    out = []
    for stage in sorted(groups):
        n, k, missing = groups[stage]
        p, lo, hi = stats.wilson(k, n)
        out.append({"stage": stage, "label": labels[stage], "n": n, "k": k, "missing": missing,
                    "hidden": n < MIN_GROUP, "pct": None if n < MIN_GROUP else 100 * p,
                    "low": None if n < MIN_GROUP else 100 * lo, "high": None if n < MIN_GROUP else 100 * hi})
    return out


def _pairs(timelines):
    for rows in timelines.values():
        for a, b in zip(rows, rows[1:]):
            if not a["in_progress"] and b["year"] == a["year"] + 1:
                yield a, b


def transitions(timelines):
    counts = defaultdict(Counter)
    for a, b in _pairs(timelines):
        if b["in_progress"]:
            continue
        fa, fb = band(a), band(b)
        if fa and fb:
            counts[fa][fb] += 1
    rows = []
    for key, label in BANDS:
        total = sum(counts[key].values())
        cells = []
        for k2, _ in BANDS:
            n = counts[key][k2]
            cells.append({"n": n, "pct": None if total < MIN_GROUP else 100.0 * n / total})
        rows.append({"key": key, "label": label, "total": total, "cells": cells})
    stay = counts["abaixo"]["abaixo"]
    from_below = sum(counts["abaixo"].values())
    p, lo, hi = stats.wilson(stay, from_below)
    return {"bands": BANDS, "rows": rows, "n": sum(r["total"] for r in rows),
            "persist": None if from_below < MIN_GROUP else {"pct": 100 * p, "low": 100 * lo, "high": 100 * hi,
                                                            "n": from_below}}


SIGNALS = [
    ("adverse", "Terminou o ano com componente abaixo, retenção ou abandono",
     lambda a, rows: a["adverse"] == 1),
    ("retained", "Já foi retido", lambda a, rows: a["retentions_before"] + int(a["retained"]) > 0),
    ("chronic", "Presença abaixo de 90% no ano", lambda a, rows: a["chronic"]),
    ("distortion", "Distorção idade-série (2+ anos)", lambda a, rows: (a["distortion"] or 0) >= 2),
    ("drop", "Média caiu 1 ponto ou mais em relação ao ano anterior",
     lambda a, rows: a["delta"] is not None and a["delta"] <= -1),
    ("mobility", "2 ou mais mudanças de escola", lambda a, rows: a["school_changes"] >= 2),
]


def signal_validation(timelines):
    """Para cada sinal no ano t: desfecho desfavorável no ano t+1 com e sem o sinal, e o risco relativo."""
    tallies = {k: [0, 0, 0, 0] for k, _, _ in SIGNALS}  # com: desfecho, total; sem: desfecho, total
    n_pairs = 0
    for rows in timelines.values():
        for a, b in zip(rows, rows[1:]):
            if a["in_progress"] or b["year"] != a["year"] + 1:
                continue
            y = adverse(b)
            if y is None:
                continue
            n_pairs += 1
            for key, _, test in SIGNALS:
                t = tallies[key]
                if test(a, rows):
                    t[0] += y
                    t[1] += 1
                else:
                    t[2] += y
                    t[3] += 1
    out = []
    for key, label, _ in SIGNALS:
        a, n1, c, n0 = tallies[key]
        hidden = n1 < MIN_GROUP or n0 < MIN_GROUP
        with_ = stats.wilson(a, n1)
        without = stats.wilson(c, n0)
        rr = None if hidden else stats.risk_ratio(a, n1, c, n0)
        out.append({"key": key, "label": label, "n_with": n1, "n_without": n0, "hidden": hidden,
                    "with": None if hidden else [100 * v for v in with_],
                    "without": None if hidden else [100 * v for v in without], "rr": rr,
                    "clear": bool(rr and (rr["low"] > 1 or rr["high"] < 1))})
    return {"pairs": n_pairs, "rows": out}


def stability(timelines):
    xs, ys = [], []
    for a, b in _pairs(timelines):
        if b["in_progress"] or a["average"] is None or b["average"] is None:
            continue
        xs.append(a["average"])
        ys.append(b["average"])
    rho = stats.spearman(xs, ys) if len(xs) >= MIN_GROUP else None
    return {"n": len(xs), "rho": rho}


def coverage(timelines):
    """Quantos estudantes têm anos anteriores e quantos anos a escola tem de histórico."""
    years = Counter()
    with_prior = 0
    for rows in timelines.values():
        if any(r["source"] == "historico" for r in rows):
            with_prior += 1
        for r in rows:
            years[r["year"]] += 1
    return {"students": len(timelines), "with_prior": with_prior, "years": sorted(years.items())}
