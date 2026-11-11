"""Estatística em Python puro, usada em toda a plataforma (sem dependência nova, custo zero).

Cada função cita o método. Quem chama decide o que mostrar; aqui só a conta.

- **Proporções:** intervalo de Wilson (Wilson, 1927, JASA 22(158), 209–212), com correção de população finita
  quando se conhece o total (consulta a 120 famílias, das quais 74 responderam).
- **Diferença entre duas médias:** teste de Welch, que não supõe variâncias iguais (Welch, 1947, Biometrika
  34(1–2), 28–35), e tamanho de efeito g de Hedges com IC (Hedges, 1981, Journal of Educational Statistics 6(2),
  107–128).
- **Muitas comparações ao mesmo tempo:** taxa de falsas descobertas de Benjamini & Hochberg (1995, JRSS B 57(1),
  289–300). Comparar 10 turmas a 5% cada dá, por acaso, uma "diferença" quase sempre.
- **Confiabilidade de uma prova:** alfa de Cronbach (Cronbach, 1951, Psychometrika 16(3), 297–334), lido como
  limite inferior da confiabilidade e nada além disso (Sijtsma, 2009, Psychometrika 74(1), 107–120,
  doi:10.1007/s11336-008-9101-0); erro-padrão de medida = DP·√(1 − α).
- **Discriminação de uma questão:** correlação questão × total das OUTRAS questões (correlação item-total
  corrigida), para a questão não se correlacionar consigo mesma.
- **Controle estatístico de processo:** carta p′ de Laney (2002, Quality Engineering 14(4), 531–537), que alarga
  os limites da carta p quando há variação extra entre semanas (com milhares de chamadas por semana, a carta p
  comum acusaria "causa especial" toda semana); regras de sequência de Anhøj & Olesen (2014, PLoS ONE 9(11):
  e113825, doi:10.1371/journal.pone.0113825): sequência longa do mesmo lado da mediana e poucos cruzamentos, com
  ~5% de alarme falso qualquer que seja o número de pontos.
"""

import math
from statistics import mean, median

Z95 = 1.959964


# ---------------------------------------------------------------- proporções

def wilson(k, n, z=Z95, population=None):
    """(proporção, limite inferior, limite superior). ``population``: total conhecido (correção finita)."""
    if not n:
        return None, None, None
    p = k / n
    fpc = 1.0
    if population and population > 1 and n <= population:
        fpc = math.sqrt(max(population - n, 0) / (population - 1))
    zz = z * fpc
    if zz == 0:
        return p, p, p
    den = 1 + zz * zz / n
    centre = (p + zz * zz / (2 * n)) / den
    half = zz * math.sqrt(p * (1 - p) / n + zz * zz / (4 * n * n)) / den
    return p, max(0.0, centre - half), min(1.0, centre + half)


def diff_of_shares(k1, k2, n, z=Z95, population=None):
    """IC da diferença entre duas opções da MESMA votação (multinomial): var = (p1 + p2 − (p1 − p2)²)/n."""
    if not n:
        return None
    p1, p2 = k1 / n, k2 / n
    var = (p1 + p2 - (p1 - p2) ** 2) / n
    if population and population > 1 and n <= population:
        var *= max(population - n, 0) / (population - 1)
    half = z * math.sqrt(max(var, 0))
    return {"diff": p1 - p2, "low": p1 - p2 - half, "high": p1 - p2 + half}


# ---------------------------------------------------------------- distribuição t (beta incompleta)

def _betacf(a, b, x):
    """Fração contínua da beta incompleta (Lentz modificado)."""
    tiny, qab, qap, qam = 1e-300, a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c if abs(1 + aa / c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c if abs(1 + aa / c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-12:
            break
    return h


def betainc(a, b, x):
    """Beta incompleta regularizada I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbeta) * _betacf(a, b, x) / a
    return 1 - math.exp(lbeta) * _betacf(b, a, 1 - x) / b


def t_two_sided_p(t, df):
    if df <= 0 or t is None or math.isnan(t):
        return None
    return betainc(df / 2, 0.5, df / (df + t * t))


def _var(xs):
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def welch(a, b):
    """{"t", "df", "p"} do teste de Welch para as médias de ``a`` e ``b`` (2+ valores em cada)."""
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = _var(a) / len(a), _var(b) / len(b)
    se = math.sqrt(va + vb)
    if se == 0:
        return {"t": 0.0, "df": len(a) + len(b) - 2, "p": 1.0 if mean(a) == mean(b) else 0.0}
    t = (mean(a) - mean(b)) / se
    df = (va + vb) ** 2 / ((va ** 2 / (len(a) - 1)) + (vb ** 2 / (len(b) - 1))) if va and vb else len(a) + len(b) - 2
    return {"t": t, "df": df, "p": t_two_sided_p(t, df)}


def hedges_g(a, b, z=Z95):
    """g de Hedges (d de Cohen com correção de viés para amostras pequenas) e IC 95% aproximado."""
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return None
    sp = math.sqrt(((n1 - 1) * _var(a) + (n2 - 1) * _var(b)) / (n1 + n2 - 2))
    if sp == 0:
        return None
    d = (mean(a) - mean(b)) / sp
    j = 1 - 3 / (4 * (n1 + n2) - 9)
    g = j * d
    se = math.sqrt((n1 + n2) / (n1 * n2) + g * g / (2 * (n1 + n2)))
    return {"g": g, "low": g - z * se, "high": g + z * se}


def benjamini_hochberg(pvalues):
    """Valores q (p ajustados pela taxa de falsas descobertas), na mesma ordem; None continua None."""
    order = sorted((i for i, p in enumerate(pvalues) if p is not None), key=lambda i: pvalues[i])
    m = len(order)
    q = [None] * len(pvalues)
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvalues[i] * m / rank)
        q[i] = running
    return q


def effect_label(g):
    """Rótulo convencional de Cohen (1988) para |g|: só referência, não régua pedagógica."""
    a = abs(g)
    return "desprezível" if a < 0.2 else "pequena" if a < 0.5 else "média" if a < 0.8 else "grande"


# ---------------------------------------------------------------- precisão de uma média

def weighted_mean_se(values, weights=None):
    """(média, erro-padrão) de uma média ponderada; com pesos iguais o EP é s/√n."""
    n = len(values)
    if n < 2:
        return (values[0] if values else None), None
    w = weights or [1.0] * n
    sw = sum(w)
    if not sw:
        return None, None
    m = sum(x * wi for x, wi in zip(values, w)) / sw
    var = sum((wi ** 2) * (x - m) ** 2 for x, wi in zip(values, w)) / (sw ** 2) * n / (n - 1)
    return m, math.sqrt(var)


# ---------------------------------------------------------------- análise de itens

def pearson(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if not sxx or not syy:
        return None
    return sxy / math.sqrt(sxx * syy)


def item_analysis(matrix):
    """``matrix``: uma linha por estudante (todos com todas as questões), valores de 0 a 1 por questão.

    Devolve alfa de Cronbach, erro-padrão de medida (na escala 0–1 da prova inteira, em fração da nota máxima) e,
    por questão, a correlação item-total corrigida e o alfa se a questão saísse.
    """
    n = len(matrix)
    k = len(matrix[0]) if matrix else 0
    if n < 2 or k < 2:
        return None
    cols = [[row[j] for row in matrix] for j in range(k)]
    totals = [sum(row) for row in matrix]

    def alpha(cols_, totals_):
        kk = len(cols_)
        vt = _var(totals_) if len(totals_) > 1 else 0
        if kk < 2 or not vt:
            return None
        return kk / (kk - 1) * (1 - sum(_var(c) for c in cols_) / vt)

    a = alpha(cols, totals)
    items = []
    for j in range(k):
        rest = [t - x for t, x in zip(totals, cols[j])]
        others = cols[:j] + cols[j + 1:]
        items.append({"r_rest": pearson(cols[j], rest), "alpha_without": alpha(others, rest),
                      "facility": mean(cols[j])})
    sd_total = math.sqrt(_var(totals)) / k if n > 1 else None
    sem = sd_total * math.sqrt(1 - a) if a is not None and a < 1 and sd_total is not None else None
    return {"alpha": a, "sem": sem, "sd": sd_total, "n": n, "k": k, "items": items}


# ---------------------------------------------------------------- controle estatístico de processo

def laney_p(points):
    """Carta p′ de Laney. ``points``: [(rótulo, acertos, total)]. Devolve linha central, σ_z e limites por ponto."""
    pts = [(lab, k, n) for lab, k, n in points if n]
    if len(pts) < 2:
        return None
    pbar = sum(k for _, k, _ in pts) / sum(n for _, _, n in pts)
    if pbar in (0, 1):
        return None
    z = [((k / n) - pbar) / math.sqrt(pbar * (1 - pbar) / n) for _, k, n in pts]
    mr = [abs(b - a) for a, b in zip(z, z[1:])]
    sigma_z = (mean(mr) / 1.128) if mr else 1.0
    rows = []
    for (lab, k, n), zi in zip(pts, z):
        s = math.sqrt(pbar * (1 - pbar) / n) * sigma_z
        lo, hi = max(0.0, pbar - 3 * s), min(1.0, pbar + 3 * s)
        p = k / n
        rows.append({"label": lab, "p": p, "n": n, "low": lo, "high": hi,
                     "signal": "abaixo" if p < lo else "acima" if p > hi else None})
    return {"center": pbar, "sigma_z": sigma_z, "points": rows}


def anhoej(values):
    """Regras de Anhøj em torno da mediana: sequência mais longa e número de cruzamentos (pontos na mediana saem)."""
    if len(values) < 2:
        return None
    med = median(values)
    sides = [1 if v > med else -1 for v in values if v != med]
    n = len(sides)
    if n < 2:
        return None
    longest = run = 1
    crossings = 0
    for a, b in zip(sides, sides[1:]):
        if a == b:
            run += 1
        else:
            crossings += 1
            run = 1
        longest = max(longest, run)
    run_limit = round(math.log2(n) + 3)
    # menor c tal que P(X ≤ c) ≥ 0,05 com X ~ Binomial(n − 1, 0,5), menos 1: abaixo disso, poucos cruzamentos
    cum, min_cross = 0.0, 0
    for c in range(n):
        cum += math.comb(n - 1, c) * 0.5 ** (n - 1)
        if cum >= 0.05:
            min_cross = c
            break
    return {"median": med, "n": n, "longest": longest, "run_limit": run_limit, "crossings": crossings,
            "min_crossings": min_cross, "shift": longest > run_limit, "few_crossings": crossings < min_cross}
