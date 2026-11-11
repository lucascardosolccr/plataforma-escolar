"""Previsão para o ano letivo: a chance de o ano terminar com desfecho desfavorável, a partir dos anos anteriores.

Pergunta: no começo do ano, com o que já se sabe do estudante até o ano passado, quem tem mais chance de terminar
este ano com retenção, abandono ou algum componente abaixo da média? É a pergunta dos indicadores "on-track" de
entrada (Allensworth & Easton, 2005, *The On-Track Indicator as a Predictor of High School Graduation*,
Consortium on Chicago School Research): agir antes, não depois do primeiro boletim.

Método (relatado conforme o TRIPOD: Collins, Reitsma, Altman & Moons, 2015, BMJ 350:g7594,
doi:10.1136/bmj.g7594):

- **Exemplos:** pares de anos seguidos (t, t+1) de cada estudante. Atributos só do ano t e antes; desfecho do
  ano t+1 (``timeline.adverse``). Transferido no meio do ano fica de fora (desfecho não observado).
- **Atributos (6):** média geral, número de componentes abaixo da média, frequência, retenções até então,
  distorção idade-série e variação da média em relação ao ano anterior. Nada de dado pessoal sensível, de
  inclusão, saúde, cor, renda, gênero ou família. Valor ausente vira a média do treino (variação ausente = 0).
- **Modelo:** regressão logística com penalidade ridge, atributos padronizados (``stats.fit_logistic``).
  Escolhida por ser explicável: a contribuição de cada atributo para a previsão é exata e aparece na tela.
- **Validação temporal:** treino com os anos-alvo anteriores e teste com o ano-alvo mais recente, como seria
  usado de verdade (prever o futuro com o passado). Depois de validado, o modelo é reajustado com todos os anos.
- **Tamanho mínimo:** 10 desfechos (da classe menos frequente) por atributo no treino (Peduzzi et al., 1996,
  Journal of Clinical Epidemiology 49(12), 1373–1379, doi:10.1016/s0895-4356(96)00236-3) e, no teste, 50
  estudantes com 10 de cada desfecho. Abaixo disso: "dados insuficientes", e nenhuma probabilidade aparece.
- **Métricas:** AUC com IC 95% (Hanley & McNeil, 1982), Brier e Brier relativo à taxa base, intercepto e
  inclinação de calibração (Van Calster et al., 2019) e tabela de calibração. Comparação com a referência
  ingênua "o ano que vem repete o ano passado": se o modelo não for melhor que ela, a tela diz para usar a regra.
- **Uso:** só depois de a direção aprovar uma validação que passou nos critérios técnicos. Família e estudante
  nunca veem a previsão. A previsão não decide nada (LGPD art. 20): orienta onde começar o apoio, e o
  diagnóstico ao lado mostra os fatos que a sustentam.

Limite que a tela repete: expectativa do professor pode influenciar o desempenho, ainda que o efeito médio seja
pequeno (Jussim & Harber, 2005, Personality and Social Psychology Review 9(2), 131–155). Por isso a previsão vem
com o que fazer, não com um rótulo.
"""

import datetime
import math
from statistics import mean, pstdev

from django.utils import timezone

from apps.cognitio.models import ModelRun

from . import stats
from .timeline import adverse, build_many, students_of

NAME, VERSION = "trajetoria_ano_letivo", "1.0"
EPV = 10
MIN_TEST, MIN_TEST_EACH = 50, 10
MIN_AUC, MIN_AUC_LOW = 0.70, 0.60
CAL_SLOPE = (0.7, 1.4)
L2 = 1.0

FEATURES = [
    ("average", "Média geral do ano anterior"),
    ("n_below", "Componentes abaixo da média no ano anterior"),
    ("attendance", "Frequência no ano anterior"),
    ("retentions", "Retenções até o ano anterior"),
    ("distortion", "Distorção idade-série (anos)"),
    ("delta", "Variação da média de um ano para o outro"),
]


def features(row):
    """Atributos do ano ``row`` (ano t), com None onde falta dado."""
    return {
        "average": row["average"],
        "n_below": float(row["n_below"]) if row["subjects"] else None,
        "attendance": row["attendance"],
        "retentions": float(row["retentions_before"] + (1 if row["retained"] else 0)),
        "distortion": float(row["distortion"]) if row["distortion"] is not None else None,
        "delta": row["delta"] if row["delta"] is not None else 0.0,
    }


def examples(timelines):
    """[(ano-alvo, atributos, desfecho, desfecho do ano t)] de todos os pares de anos seguidos."""
    out = []
    for rows in timelines.values():
        for a, b in zip(rows, rows[1:]):
            if a["in_progress"] or a["average"] is None or b["year"] != a["year"] + 1:
                continue
            y = adverse(b)
            if y is None:
                continue
            out.append((b["year"], features(a), y, adverse(a)))
    return out


def _prepare(train_feats, *others):
    """Imputação pela média do treino e padronização com média e desvio do treino."""
    keys = [k for k, _ in FEATURES]
    impute, means, sds = {}, {}, {}
    for k in keys:
        vals = [f[k] for f in train_feats if f[k] is not None]
        impute[k] = mean(vals) if vals else 0.0
    filled = [[f[k] if f[k] is not None else impute[k] for k in keys] for f in train_feats]
    for j, k in enumerate(keys):
        col = [r[j] for r in filled]
        means[k] = mean(col) if col else 0.0
        sds[k] = pstdev(col) or 1.0 if col else 1.0
    params = {"features": keys, "impute": impute, "means": means, "sds": sds}
    return params, [transform(params, f) for f in train_feats], [[transform(params, f) for f in o] for o in others]


def transform(params, feats):
    out = []
    for k in params["features"]:
        v = feats.get(k)
        v = params["impute"][k] if v is None else v
        out.append((v - params["means"][k]) / params["sds"][k])
    return out


def _evaluate(y, p, base_rate):
    a = stats.auc(y, p)
    pos = sum(y)
    lo, hi = stats.auc_ci(a, pos, len(y) - pos)
    b = stats.brier(y, p)
    b_ref = stats.brier(y, [base_rate] * len(y))
    cal_int, cal_slope = stats.calibration(y, p)
    return {"auc": a, "auc_low": lo, "auc_high": hi, "brier": b, "brier_ref": b_ref,
            "bss": (1 - b / b_ref) if b_ref else None, "cal_intercept": cal_int, "cal_slope": cal_slope,
            "calibration": stats.calibration_table(y, p), "confusion": stats.confusion(y, p, base_rate)}


def validate(timelines):
    """Treina, valida no tempo e devolve o resultado (sem gravar)."""
    data = examples(timelines)
    years = sorted({t for t, *_ in data})
    result = {"examples": len(data), "years": years, "status": ModelRun.Status.INSUFFICIENT, "reasons": []}
    if len(years) < 2:
        result["reasons"].append("É preciso ter pelo menos dois anos-alvo com desfecho (três anos seguidos de "
                                 "histórico): um para treinar e o mais recente para testar.")
        return result
    test_year = years[-1]
    train = [d for d in data if d[0] < test_year]
    test = [d for d in data if d[0] == test_year]
    y_train, y_test = [d[2] for d in train], [d[2] for d in test]
    minority = min(sum(y_train), len(y_train) - sum(y_train))
    need = EPV * len(FEATURES)
    result.update({"test_year": test_year, "train_years": years[:-1], "n_train": len(train), "n_test": len(test),
                   "train_events": minority, "test_pos": sum(y_test), "need_events": need})
    if minority < need:
        result["reasons"].append(f"No treino há {minority} desfechos da classe menos frequente; são necessários "
                                 f"{need} (10 por atributo).")
    if len(test) < MIN_TEST or min(sum(y_test), len(y_test) - sum(y_test)) < MIN_TEST_EACH:
        result["reasons"].append(f"No teste ({test_year}) há {len(test)} estudantes e {sum(y_test)} desfechos; são "
                                 f"necessários {MIN_TEST} estudantes com {MIN_TEST_EACH} de cada desfecho.")
    if result["reasons"]:
        return result

    params, X_train, (X_test,) = _prepare([d[1] for d in train], [d[1] for d in test])
    coefs, intercept = stats.fit_logistic(X_train, y_train, l2=L2)
    p_test = stats.predict(coefs, intercept, X_test)
    base_rate = mean(y_train)
    metrics = _evaluate(y_test, p_test, base_rate)
    naive = [float(d[3]) if d[3] is not None else base_rate for d in test]
    baseline = {"name": "O ano que vem repete o ano passado", **_evaluate(y_test, naive, base_rate)}
    metrics.update({"base_rate_train": base_rate, "base_rate_test": mean(y_test)})

    reasons = []
    if metrics["auc"] is None or metrics["auc"] < MIN_AUC:
        reasons.append(f"AUC abaixo de {str(MIN_AUC).replace('.', ',')}.")
    if metrics["auc_low"] is None or metrics["auc_low"] < MIN_AUC_LOW:
        reasons.append(f"Limite inferior do IC da AUC abaixo de {str(MIN_AUC_LOW).replace('.', ',')}: a "
                       "discriminação pode ser fraca.")
    if metrics["cal_slope"] is None or not CAL_SLOPE[0] <= metrics["cal_slope"] <= CAL_SLOPE[1]:
        reasons.append("Inclinação de calibração fora de 0,7 a 1,4: as probabilidades estariam extremas ou tímidas "
                       "demais.")
    if metrics["bss"] is None or metrics["bss"] <= 0:
        reasons.append("Não erra menos que simplesmente usar a taxa média (Brier relativo ≤ 0).")
    beats = baseline["auc"] is None or metrics["auc"] >= baseline["auc"]
    if not beats:
        reasons.append("Não é melhor que a regra ingênua \"o ano que vem repete o ano passado\": use a regra.")

    # Modelo final: mesmos passos com todos os anos.
    params_all, X_all, _ = _prepare([d[1] for d in data])
    coefs_all, intercept_all = stats.fit_logistic(X_all, [d[2] for d in data], l2=L2)
    result.update({
        "status": ModelRun.Status.EXPERIMENTAL, "approvable": not reasons, "reasons": reasons,
        "metrics": metrics, "baseline": baseline,
        "validation_model": {"coefs": coefs, "intercept": intercept, **params},
        "model": {"coefs": coefs_all, "intercept": intercept_all, **params_all},
        "test_predictions": sorted(zip(p_test, y_test)),
    })
    return result


def _jsonable(obj):
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else round(obj, 6)
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def run(school, user=None, student_ids=None, today=None):
    """Valida com os dados da escola e grava um ``ModelRun`` (auditoria e monitoramento)."""
    timelines = build_many(school, students_of(school, student_ids), today)
    res = validate(timelines)
    metrics = {k: res.get(k) for k in ("examples", "years", "test_year", "train_years", "train_events",
                                       "need_events", "test_pos", "reasons", "approvable")}
    metrics.update(res.get("metrics", {}))
    return ModelRun.objects.create(
        school=school, name=NAME, version=VERSION,
        cutoff=datetime.date(res["test_year"], 1, 1) if res.get("test_year") else None,
        n_train=res.get("n_train", 0), n_test=res.get("n_test", 0), positives=res.get("test_pos", 0) or 0,
        metrics=_jsonable(metrics), baseline=_jsonable(res.get("baseline", {})),
        coefficients=_jsonable(res.get("model", {})), status=res["status"],
        notes=f"Treinado por {user} em {timezone.localdate():%d/%m/%Y}." if user else "")


def runs(school):
    return ModelRun.objects.filter(school=school, name=NAME).order_by("-created_at")


def active_run(school):
    return runs(school).filter(status=ModelRun.Status.APPROVED).first()


def predict_for(rows, run, today=None):
    """Previsão para o ano em andamento a partir do último ano completo, com a contribuição de cada atributo."""
    if run is None or not run.coefficients.get("coefs"):
        return None
    today = today or timezone.localdate()
    current = next((r for r in reversed(rows) if r["in_progress"]), None)
    target_year = current["year"] if current else today.year
    prev = next((r for r in reversed(rows) if r["year"] == target_year - 1 and not r["in_progress"]), None)
    if prev is None or prev["average"] is None:
        return None
    m = run.coefficients
    feats = features(prev)
    z = transform(m, feats)
    lp = m["intercept"] + sum(c * v for c, v in zip(m["coefs"], z))
    p = stats.sigmoid(lp)
    labels = dict(FEATURES)
    contrib = sorted(({"label": labels[k], "value": feats[k], "effect": c * v, "key": k}
                      for k, c, v in zip(m["features"], m["coefs"], z)), key=lambda d: -abs(d["effect"]))
    bin_ = next((b for b in run.metrics.get("calibration", []) if b["from"] <= p <= b["to"]), None)
    return {"probability": p, "year": target_year, "from_year": prev["year"], "factors": contrib[:3],
            "bin": bin_, "base_rate": run.metrics.get("base_rate_test")}


def synthetic_timelines(n_students=400, years=(2022, 2023, 2024, 2025), noise=False, seed=11):
    """Linhas do tempo sintéticas com efeito conhecido (testes e demonstração do método, nunca dado real)."""
    import random

    rnd = random.Random(seed)
    out = {}
    for i in range(n_students):
        ability = rnd.gauss(0, 1)
        att_trait = rnd.gauss(0, 1)
        rows, retentions = [], 0
        for year in years:
            avg = max(0.0, min(10.0, 6.8 + 1.3 * ability + rnd.gauss(0, 0.8)))
            att = max(50.0, min(100.0, 93 + 4 * att_trait + rnd.gauss(0, 2)))
            n_below = sum(1 for _ in range(8) if rnd.gauss(avg, 1.2) < 6)
            if noise:
                bad = rnd.random() < 0.35
            else:
                lp = -0.6 - 1.4 * ability - 0.5 * att_trait + 0.6 * retentions + rnd.gauss(0, 0.3)
                bad = rnd.random() < stats.sigmoid(lp)
            retained = bad and rnd.random() < 0.25
            subjects = [{"value": avg, "below": bad and k < max(1, n_below)} for k in range(8)]
            rows.append({"year": year, "in_progress": False, "average": avg, "subjects": subjects,
                         "n_below": sum(1 for s in subjects if s["below"]), "attendance": att,
                         "retentions_before": retentions, "retained": retained, "distortion": retentions,
                         "outcome": "reprovado" if retained else "aprovado", "promoted": not retained,
                         "delta": None})
            retentions += int(retained)
        for a, b in zip(rows, rows[1:]):
            b["delta"] = b["average"] - a["average"]
        out[i] = rows
    return out
