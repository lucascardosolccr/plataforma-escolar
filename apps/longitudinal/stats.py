"""Estatística em Python puro (sem dependência nova) para a trajetória escolar.

- **Intervalo de Wilson** para proporções (Wilson, 1927, JASA 22(158), 209–212): continua correto com poucos
  casos e proporções perto de 0 ou 1, onde o intervalo "p ± 1,96·EP" sai do lugar.
- **Risco relativo com IC pelo logaritmo** (Katz et al., 1978, Biometrics 34(3), 469–474): quantas vezes o
  desfecho é mais frequente com o sinal do que sem ele.
- **Correlação de Spearman**: de Pearson calculada sobre os postos, robusta a notas atípicas.
- **Regressão logística penalizada (ridge)** por Newton–Raphson (mínimos quadrados reponderados): converge em
  poucas iterações e dá o mesmo resultado em qualquer máquina. A penalidade reduz o sobreajuste em amostras
  pequenas, e o intercepto não é penalizado.
- **AUC com erro-padrão de Hanley & McNeil** (1982, Radiology 143(1), 29–36).
- **Brier** (1950, Monthly Weather Review 78(1), 1–3) e **calibração** pelo intercepto e pela inclinação da
  recalibração logística (Van Calster et al., 2019, BMC Medicine 17:230, doi:10.1186/s12916-019-1466-7).
- **Curva de retenção de Kaplan–Meier** (1958) para o tempo até o abandono: ver ``core.stats.kaplan_meier``,
  reexportada aqui para ``cohort.survival_curve``.
"""

import math
from statistics import mean

from apps.core.stats import Z95, kaplan_meier, pearson, wilson  # noqa: F401 (reexportados para cohort)


def risk_ratio(a, n1, c, n0, z=Z95):
    """RR de a/n1 (com o sinal) contra c/n0 (sem), com IC 95%. Zero numa casela: correção de 0,5 (Haldane)."""
    if not n1 or not n0:
        return None
    if a == 0 or c == 0 or a == n1 or c == n0:
        a, c, n1, n0 = a + 0.5, c + 0.5, n1 + 1, n0 + 1
    p1, p0 = a / n1, c / n0
    rr = p1 / p0
    se = math.sqrt(max(1 / a - 1 / n1 + 1 / c - 1 / n0, 0))
    return {"rr": rr, "low": math.exp(math.log(rr) - z * se), "high": math.exp(math.log(rr) + z * se)}


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs, ys):
    return pearson(_ranks(xs), _ranks(ys)) if len(xs) >= 3 else None


def _solve(a, b):
    """Resolve a·x = b por eliminação de Gauss com pivotamento parcial (sistemas pequenos)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            raise ValueError("sistema singular")
        m[col], m[piv] = m[piv], m[col]
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def sigmoid(z):
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def fit_logistic(X, y, l2=1.0, max_iter=50, tol=1e-8):
    """(coeficientes, intercepto) da regressão logística com penalidade l2·Σβ² (intercepto livre)."""
    k = len(X[0]) if X else 0
    beta = [0.0] * (k + 1)  # beta[0] = intercepto
    rows = [[1.0] + list(x) for x in X]
    for _ in range(max_iter):
        p = [sigmoid(sum(b * v for b, v in zip(beta, r))) for r in rows]
        grad = [sum((yi - pi) * r[j] for r, yi, pi in zip(rows, y, p)) - (2 * l2 * beta[j] if j else 0.0)
                for j in range(k + 1)]
        hess = [[sum(pi * (1 - pi) * r[i] * r[j] for r, pi in zip(rows, p)) + (2 * l2 if i == j and i else 0.0)
                 for j in range(k + 1)] for i in range(k + 1)]
        step = _solve(hess, grad)
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < tol:
            break
    return beta[1:], beta[0]


def predict(coefs, intercept, X):
    return [sigmoid(intercept + sum(c * v for c, v in zip(coefs, x))) for x in X]


def auc(y, scores):
    pos = [s for s, t in zip(scores, y) if t]
    neg = [s for s, t in zip(scores, y) if not t]
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > q else 0.5 if p == q else 0.0 for p in pos for q in neg)
    return wins / (len(pos) * len(neg))


def auc_ci(a, n_pos, n_neg, z=Z95):
    """IC 95% da AUC pelo erro-padrão de Hanley & McNeil (1982)."""
    if a is None or not n_pos or not n_neg:
        return None, None
    q1, q2 = a / (2 - a), 2 * a * a / (1 + a)
    var = (a * (1 - a) + (n_pos - 1) * (q1 - a * a) + (n_neg - 1) * (q2 - a * a)) / (n_pos * n_neg)
    se = math.sqrt(max(var, 0))
    return max(0.0, a - z * se), min(1.0, a + z * se)


def brier(y, p):
    return sum((pi - yi) ** 2 for yi, pi in zip(y, p)) / len(y) if y else None


def calibration(y, p):
    """Intercepto e inclinação da recalibração logística: ideal 0 e 1. Inclinação < 1 = previsões extremas demais
    (sobreajuste); > 1 = tímidas demais. Intercepto ≠ 0 = o modelo erra o nível geral do risco."""
    if len(set(y)) < 2:
        return None, None
    lp = [[math.log(min(max(pi, 1e-6), 1 - 1e-6) / (1 - min(max(pi, 1e-6), 1 - 1e-6)))] for pi in p]
    try:
        coefs, intercept = fit_logistic(lp, y, l2=0.0)
    except ValueError:
        return None, None
    return intercept, coefs[0]


def calibration_table(y, p, bins=5):
    """Faixas por quantil das previsões: previsto médio × observado (com IC de Wilson)."""
    pairs = sorted(zip(p, y))
    n = len(pairs)
    out = []
    for b in range(bins):
        part = pairs[b * n // bins:(b + 1) * n // bins]
        if not part:
            continue
        k = sum(t for _, t in part)
        obs, lo, hi = wilson(k, len(part))
        out.append({"n": len(part), "predicted": mean(pp for pp, _ in part), "observed": obs, "low": lo, "high": hi,
                    "from": part[0][0], "to": part[-1][0]})
    return out


def confusion(y, p, threshold):
    tp = sum(1 for t, s in zip(y, p) if t and s >= threshold)
    fp = sum(1 for t, s in zip(y, p) if not t and s >= threshold)
    fn = sum(1 for t, s in zip(y, p) if t and s < threshold)
    tn = sum(1 for t, s in zip(y, p) if not t and s < threshold)

    def ratio(a, b):
        return a / b if b else None

    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "sensitivity": ratio(tp, tp + fn),
            "specificity": ratio(tn, tn + fp), "ppv": ratio(tp, tp + fp), "npv": ratio(tn, tn + fn)}
