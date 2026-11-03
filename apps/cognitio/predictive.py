"""Modelo preditivo experimental: risco de dificuldade numa habilidade subsequente.

Pergunta: dado o estado de um estudante num pré-requisito (relação do grafo), qual
a chance de ele ter dificuldade na habilidade que pode depender dele, quando ela
for avaliada depois?

Método (puro Python, sem dependência nova):
- exemplos: pares (estudante, pré-requisito A → habilidade B) em que A tem
  evidência ANTES da primeira evidência de B (sem vazamento: só entram dados de
  A anteriores a B);
- rótulo: B com média ponderada abaixo do corte de dificuldade nas primeiras
  evidências;
- atributos: média em A, A em dificuldade, nº de evidências de A, confiança da
  relação; nada de dado pessoal, de inclusão ou de saúde;
- regressão logística com regularização L2, atributos padronizados;
- separação TEMPORAL: treino com pares cuja B foi avaliada antes do corte, teste
  com os posteriores;
- comparação com a referência simples (regra: "A em dificuldade → B em
  dificuldade") e com a taxa base;
- métricas: precisão, revocação (sensibilidade), especificidade, F1, acurácia,
  Brier, AUC e calibração por faixas.

Só sai do modo exploratório com dados suficientes (``MIN_TRAIN``, ``MIN_POS``,
``MIN_TEST``) E com aprovação humana registrada. Com dados sintéticos ou da base
de demonstração, o resultado NÃO demonstra eficácia real.
"""

import math
import random

from django.utils import timezone

from apps.core.fmt import dec

from .mastery import assess
from .models import MasteryScale, ModelRun, SkillEvidence

NAME = "risco_dificuldade_subsequente"
VERSION = "1.0"
MIN_TRAIN, MIN_POS, MIN_TEST = 200, 30, 50


def build_dataset(school):
    from .graph import _visible
    from .models import SkillRelation

    scale = MasteryScale.for_school(school)
    rels = list(_visible(SkillRelation.objects.all(), school))
    by_si = {}
    for e in SkillEvidence.objects.filter(school=school).order_by("observed_on"):
        by_si.setdefault((e.student_id, e.item_id), []).append(e)
    students = {sid for sid, _ in by_si}
    rows = []
    for rel in rels:
        for sid in students:
            b = by_si.get((sid, rel.target_id))
            a = by_si.get((sid, rel.source_id))
            if not a or not b:
                continue
            b_valid = [e for e in b if e.ratio is not None]
            if not b_valid:
                continue
            t_b = b_valid[0].observed_on
            a_before = [e for e in a if e.observed_on < t_b]
            if not [e for e in a_before if e.ratio is not None]:
                continue
            sa = assess(a_before, scale, today=t_b)
            first_b = b_valid[:3]
            mb = sum(e.ratio for e in first_b) / len(first_b)
            rows.append({"date": t_b, "y": 1 if mb < float(scale.t1) else 0,
                         "x": [sa.mean or 0.0, 1.0 if sa.state == "dificuldade" else 0.0, float(sa.n_valid),
                               {"alta": 1.0, "media": 0.5}.get(rel.confidence, 0.0)],
                         "rule": 1 if sa.state == "dificuldade" else 0})
    return rows


def _standardize(train, test):
    k = len(train[0]["x"])
    mu = [sum(r["x"][j] for r in train) / len(train) for j in range(k)]
    sd = [math.sqrt(sum((r["x"][j] - mu[j]) ** 2 for r in train) / len(train)) or 1.0 for j in range(k)]
    f = lambda r: [(r["x"][j] - mu[j]) / sd[j] for j in range(k)]
    return [f(r) for r in train], [f(r) for r in test], mu, sd


def fit_logistic(X, y, l2=0.1, lr=0.1, epochs=400):
    k = len(X[0])
    w, b = [0.0] * k, 0.0
    n = len(X)
    for _ in range(epochs):
        gw, gb = [0.0] * k, 0.0
        for xi, yi in zip(X, y):
            z = b + sum(wj * xj for wj, xj in zip(w, xi))
            p = 1 / (1 + math.exp(-max(min(z, 30), -30)))
            d = p - yi
            gb += d
            for j in range(k):
                gw[j] += d * xi[j]
        b -= lr * gb / n
        w = [wj - lr * (gwj / n + l2 * wj) for wj, gwj in zip(w, gw)]
    return w, b


def predict(w, b, X):
    return [1 / (1 + math.exp(-max(min(b + sum(a * c for a, c in zip(w, x)), 30), -30))) for x in X]


def metrics(y, scores, threshold=0.5):
    pred = [1 if s >= threshold else 0 for s in scores]
    tp = sum(1 for a, b in zip(y, pred) if a == 1 and b == 1)
    tn = sum(1 for a, b in zip(y, pred) if a == 0 and b == 0)
    fp = sum(1 for a, b in zip(y, pred) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(y, pred) if a == 1 and b == 0)
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    spec = tn / (tn + fp) if tn + fp else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
    out = {"tp": tp, "tn": tn, "fp": fp, "fn": fn, "precisao": prec, "revocacao": rec, "especificidade": spec,
           "f1": f1, "acuracia": (tp + tn) / len(y) if y else None,
           "brier": sum((s - a) ** 2 for a, s in zip(y, scores)) / len(y) if y else None}
    pos = [s for a, s in zip(y, scores) if a == 1]
    neg = [s for a, s in zip(y, scores) if a == 0]
    if pos and neg:
        wins = sum(1.0 if p > q else 0.5 if p == q else 0.0 for p in pos for q in neg)
        out["auc"] = wins / (len(pos) * len(neg))
    bins = []
    for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
        sel = [(a, s) for a, s in zip(y, scores) if lo <= s < lo + 0.2 or (lo == 0.8 and s == 1.0)]
        if sel:
            bins.append({"faixa": f"{dec(lo, 1)}–{dec(lo + 0.2, 1)}", "n": len(sel),
                         "previsto": sum(s for _, s in sel) / len(sel), "observado": sum(a for a, _ in sel) / len(sel)})
    out["calibracao"] = bins
    return out


def train_and_validate(school, user=None):
    """Treina, valida no período posterior e registra um ``ModelRun``."""
    rows = sorted(build_dataset(school), key=lambda r: r["date"])
    positives = sum(r["y"] for r in rows)
    run = ModelRun(school=school, name=NAME, version=VERSION, positives=positives)
    if len(rows) < MIN_TRAIN + MIN_TEST or positives < MIN_POS:
        run.status = ModelRun.Status.INSUFFICIENT
        run.n_train = len(rows)
        run.notes = (f"{len(rows)} exemplos e {positives} casos de dificuldade. São necessários pelo menos "
                     f"{MIN_TRAIN + MIN_TEST} exemplos e {MIN_POS} casos para treinar e testar com separação temporal. "
                     "Os alertas continuam como regras pedagógicas explícitas, sem probabilidade.")
        run.save()
        return run
    cut = int(len(rows) * 0.7)
    train, test = rows[:cut], rows[cut:]
    run.cutoff = test[0]["date"]
    run.n_train, run.n_test = len(train), len(test)
    Xtr, Xte, mu, sd = _standardize(train, test)
    w, b = fit_logistic(Xtr, [r["y"] for r in train])
    yte = [r["y"] for r in test]
    run.metrics = metrics(yte, predict(w, b, Xte))
    base_rate = sum(r["y"] for r in train) / len(train)
    run.baseline = {"regra": metrics(yte, [float(r["rule"]) for r in test]),
                    "taxa_base": metrics(yte, [base_rate] * len(test))}
    run.coefficients = {"pesos": w, "intercepto": b, "media": mu, "desvio": sd,
                        "atributos": ["média no pré-requisito", "pré-requisito em dificuldade",
                                      "nº de evidências do pré-requisito", "confiança da relação"]}
    better = (run.metrics.get("auc") or 0) > (run.baseline["regra"].get("auc") or 0.5)
    run.status = ModelRun.Status.EXPERIMENTAL
    run.notes = ("Validado tecnicamente com separação temporal. "
                 + ("Superou a regra simples em AUC. " if better else "NÃO superou a regra simples em AUC: "
                                                                     "preferir a regra. ")
                 + "Uso em alertas só depois de aprovação pedagógica registrada.")
    run.save()
    return run


def synthetic_check(n=600, seed=7):
    """Verificação técnica do algoritmo com dados SINTÉTICOS (não reais).

    Serve só para testar que o código recupera um padrão conhecido; não diz nada
    sobre eficácia em estudantes reais.
    """
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        m = rnd.random()
        diff = 1.0 if m < 0.4 else 0.0
        p = 1 / (1 + math.exp(-(-1.5 + 3.0 * diff - 1.0 * m)))
        rows.append({"x": [m, diff, float(rnd.randint(1, 6)), 0.5], "y": 1 if rnd.random() < p else 0,
                     "rule": int(diff)})
    train, test = rows[: int(n * 0.7)], rows[int(n * 0.7):]
    Xtr, Xte, _, _ = _standardize(train, test)
    w, b = fit_logistic(Xtr, [r["y"] for r in train])
    return metrics([r["y"] for r in test], predict(w, b, Xte))


def active_run(school):
    return ModelRun.objects.filter(school=school, name=NAME, status=ModelRun.Status.APPROVED).first()
