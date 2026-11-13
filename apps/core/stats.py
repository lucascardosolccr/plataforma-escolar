"""Estatística em Python puro, usada em toda a plataforma (sem dependência nova, custo zero).

Cada função cita o método. Quem chama decide o que mostrar; aqui só a conta.

- **Proporções:** intervalo de Wilson (Wilson, 1927, JASA 22(158), 209–212), com correção de população finita
  quando se conhece o total (consulta a 120 famílias, das quais 74 responderam).
- **Diferença entre duas médias:** teste de Welch, que não supõe variâncias iguais (Welch, 1947, Biometrika
  34(1–2), 28–35), e tamanho de efeito g de Hedges com IC (Hedges, 1981, Journal of Educational Statistics 6(2),
  107–128).
- **Muitas comparações ao mesmo tempo:** taxa de falsas descobertas de Benjamini & Hochberg (1995, JRSS B 57(1),
  289–300). Comparar 10 turmas a 5% cada dá, por acaso, uma "diferença" quase sempre.
- **Comparação sem supor normalidade:** Mann–Whitney U para dois grupos (Mann & Whitney, 1947) e Kruskal–Wallis
  para três ou mais (Kruskal & Wallis, 1952), por postos. Para notas de turmas pequenas ou assimétricas, a média
  e o teste de Welch podem enganar; os testes por postos são o padrão apropriado, com tamanho de efeito
  rank-biserial (Kerby, 2014) e ε² (Tomczak & Tomczak, 2014).
- **Confiabilidade de uma prova:** alfa de Cronbach (Cronbach, 1951, Psychometrika 16(3), 297–334), lido como
  limite inferior da confiabilidade e nada além disso (Sijtsma, 2009, Psychometrika 74(1), 107–120,
  doi:10.1007/s11336-008-9101-0); erro-padrão de medida = DP·√(1 − α).
- **A mudança é real ou é ruído?** Índice de Mudança Confiável (RCI; Jacobson & Truax, 1991, Journal of
  Consulting and Clinical Psychology 59(1), 12–19, doi:10.1037/0022-006X.59.1.12): a diferença dividida pelo
  erro-padrão da diferença. |RCI| ≥ 1,96 indica mudança maior do que a flutuação esperada — em vez de um
  limiar fixo arbitrário como "1 ponto".
- **Discriminação de uma questão:** correlação questão × total das OUTRAS questões (correlação item-total
  corrigida), para a questão não se correlacionar consigo mesma.
- **Controle estatístico de processo:** carta p′ de Laney (2002, Quality Engineering 14(4), 531–537), que alarga
  os limites da carta p quando há variação extra entre semanas (com milhares de chamadas por semana, a carta p
  comum acusaria "causa especial" toda semana); regras de sequência de Anhøj & Olesen (2014, PLoS ONE 9(11):
  e113825, doi:10.1371/journal.pone.0113825): sequência longa do mesmo lado da mediana e poucos cruzamentos, com
  ~5% de alarme falso qualquer que seja o número de pontos.
"""

import math
from statistics import mean, median, quantiles

Z95 = 1.959964
MIN_OUTLIER_N = 8


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


def reliable_change(before, after, se_diff, z=Z95):
    """Índice de Mudança Confiável (RCI; Jacobson & Truax, 1991).

    Diz se a diferença ``after − before`` supera o erro de medida, em vez de depender de um
    limiar fixo e arbitrário: RCI = (after − before) / se_diff. |RCI| ≥ ``z`` (1,96 a 95%)
    indica uma mudança confiável — maior do que a flutuação esperada. ``se_diff`` é o
    erro-padrão da diferença (quem chama decide como estimá-lo a partir dos dados que tem).
    Devolve None quando ``se_diff`` não é positivo (não há base para comparar)."""
    if se_diff is None or se_diff <= 0:
        return None
    rci = (after - before) / se_diff
    return {"rci": round(rci, 2), "reliable": abs(rci) >= z, "z": z,
            "direction": "subiu" if rci > 0 else "caiu" if rci < 0 else "estável"}


# ---------------------------------------------------------------- associação entre categorias

def chi_square(table):
    """Qui-quadrado de independência (Pearson, 1900) de uma tabela de contingência (lista de listas de
    contagens). Devolve o qui-quadrado, os graus de liberdade, as contagens esperadas e a menor delas —
    a suposição clássica pede contagem esperada ≥ 5 em cada célula. Sem valor-p (para 2×2 use o exato de
    Fisher, que não depende dessa suposição)."""
    rows = len(table)
    cols = len(table[0]) if rows else 0
    if rows < 2 or cols < 2:
        return None
    row_tot = [sum(r) for r in table]
    col_tot = [sum(table[i][j] for i in range(rows)) for j in range(cols)]
    n = sum(row_tot)
    if n == 0:
        return None
    expected = [[row_tot[i] * col_tot[j] / n for j in range(cols)] for i in range(rows)]
    chi2 = sum((table[i][j] - expected[i][j]) ** 2 / expected[i][j]
               for i in range(rows) for j in range(cols) if expected[i][j] > 0)
    min_exp = min(expected[i][j] for i in range(rows) for j in range(cols))
    return {"chi2": chi2, "dof": (rows - 1) * (cols - 1), "expected": expected, "min_expected": min_exp, "n": n}


def cramers_v(table):
    """V de Cramér (Cramér, 1946): tamanho de efeito da associação entre duas variáveis categóricas, de 0
    (nenhuma) a 1 (total). V = √(χ² / (n · min(linhas−1, colunas−1)))."""
    cs = chi_square(table)
    if cs is None:
        return None
    k = min(len(table) - 1, len(table[0]) - 1)
    if k == 0:
        return None
    return math.sqrt(cs["chi2"] / (cs["n"] * k))


def fisher_exact_2x2(a, b, c, d):
    """Valor-p bicaudal do teste exato de Fisher para uma tabela 2×2 (Fisher, 1922; 1935). Soma as
    probabilidades hipergeométricas de todas as tabelas com as mesmas margens cuja probabilidade não
    excede a da tabela observada. Exato: não supõe contagens esperadas grandes."""
    n = a + b + c + d
    if n == 0:
        return None
    r1, r2, c1 = a + b, c + d, a + c

    def p_hyper(x):
        return math.comb(r1, x) * math.comb(r2, c1 - x) / math.comb(n, c1)

    p_obs = p_hyper(a)
    total = sum(px for x in range(max(0, c1 - r2), min(c1, r1) + 1)
                if (px := p_hyper(x)) <= p_obs + 1e-12)
    return min(1.0, total)


# ---------------------------------------------------------------- notas atípicas (cercas de Tukey)

def tukey_outliers(values, k=1.5):
    """Notas fora das cercas de Tukey: Q1 − k·IQR e Q3 + k·IQR, com k=1,5 (Tukey, 1977, Exploratory Data
    Analysis). Serve para apontar uma nota que destoa do conjunto — pode ser erro de lançamento ou um
    estudante que merece um olhar —, não para julgar ninguém.

    Quartis por interpolação linear (``statistics.quantiles``, método inclusivo). Precisa de ``MIN_OUTLIER_N``
    valores; abaixo disso devolve ``None`` (com poucos pontos, o IQR e as cercas são instáveis demais). Devolve
    ``q1``, ``q3``, ``iqr``, as cercas ``low``/``high`` e a contagem de atípicas abaixo/acima e no total.
    """
    vals = sorted(float(v) for v in values if v is not None)
    if len(vals) < MIN_OUTLIER_N:
        return None
    q1, _q2, q3 = quantiles(vals, n=4, method="inclusive")
    iqr = q3 - q1
    low, high = q1 - k * iqr, q3 + k * iqr
    n_low = sum(1 for v in vals if v < low)
    n_high = sum(1 for v in vals if v > high)
    return {"q1": round(q1, 2), "q3": round(q3, 2), "iqr": round(iqr, 2),
            "low": round(low, 2), "high": round(high, 2),
            "n_low": n_low, "n_high": n_high, "n_out": n_low + n_high}


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


# ---------------------------------------------- comparação não-paramétrica
# Para notas de grupos pequenos ou assimétricas, a média e o teste de Welch podem enganar:
# estes testes trabalham com postos e não supõem normalidade. Mann–Whitney compara dois
# grupos; Kruskal–Wallis, três ou mais (análogo não-paramétrico da ANOVA de um fator).

def _norm_sf(z):
    """Cauda superior da normal padrão: P(Z ≥ z)."""
    return 0.5 * math.erfc(z / math.sqrt(2))


def _gammq(a, x):
    """Função gama incompleta superior regularizada Q(a, x) (Numerical Recipes, gser/gcf)."""
    if x <= 0 or a <= 0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1.0:  # série para P(a, x); Q = 1 − P
        total = 1.0 / a
        delta = total
        ap = a
        for _ in range(300):
            ap += 1.0
            delta *= x / ap
            total += delta
            if abs(delta) < abs(total) * 1e-14:
                break
        return 1.0 - total * math.exp(-x + a * math.log(x) - gln)
    b = x + 1.0 - a  # fração contínua direta para Q(a, x)
    c, d = 1e300, 1.0 / b
    h = d
    for i in range(1, 300):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < 1e-300:
            d = 1e-300
        c = b + an / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h * math.exp(-x + a * math.log(x) - gln)


def chi2_sf(x, df):
    """Cauda superior do qui-quadrado: P(χ²_df ≥ x)."""
    if x <= 0 or df <= 0:
        return 1.0
    return _gammq(df / 2.0, x / 2.0)


def _avg_ranks(values):
    """Postos médios 1-based de ``values`` (empates recebem a média dos postos); devolve
    (postos na ordem original, Σ(t³−t) dos empates)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    tie_term = 0.0
    i = 0
    n = len(values)
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for m in range(i, j + 1):
            ranks[order[m]] = avg
        t = j - i + 1
        tie_term += t ** 3 - t
        i = j + 1
    return ranks, tie_term


def mann_whitney_u(a, b):
    """Teste de Mann–Whitney U (Wilcoxon rank-sum): compara duas amostras sem supor normalidade.

    Alternativa não-paramétrica ao teste de Welch, apropriada para notas de grupos pequenos ou
    assimétricas. p bilateral por aproximação normal com correção de empates e de continuidade
    (Mann & Whitney, 1947, Ann. Math. Statist. 18(1), 50–60). Tamanho de efeito: correlação
    rank-biserial r = 2U₁/(n₁·n₂) − 1, de −1 a 1, positivo quando ``a`` tende a ser maior
    (Kerby, 2014). ``None`` sem valor em algum dos lados.
    """
    a = [v for v in a if v is not None]
    b = [v for v in b if v is not None]
    n1, n2 = len(a), len(b)
    if n1 == 0 or n2 == 0:
        return None
    ranks, tie_term = _avg_ranks(a + b)
    r1 = sum(ranks[:n1])
    u1 = r1 - n1 * (n1 + 1) / 2.0
    big = n1 * n2
    r = 2.0 * u1 / big - 1.0
    n = n1 + n2
    mu = big / 2.0
    var = (big / 12.0) * ((n + 1) - tie_term / (n * (n - 1))) if n > 1 else 0.0
    if var <= 0:
        return {"u": u1, "p": 1.0, "rank_biserial": r, "n1": n1, "n2": n2}
    z = (abs(u1 - mu) - 0.5) / math.sqrt(var)  # correção de continuidade
    p = 2.0 * _norm_sf(max(z, 0.0))
    return {"u": u1, "p": min(1.0, p), "rank_biserial": r, "n1": n1, "n2": n2}


def kruskal_wallis(groups):
    """Teste de Kruskal–Wallis: alguma das amostras difere das demais, sem supor normalidade.

    Generaliza Mann–Whitney para 3+ grupos (análogo não-paramétrico da ANOVA de um fator;
    Kruskal & Wallis, 1952, JASA 47(260), 583–621). p por aproximação qui-quadrado com k−1 graus
    de liberdade e correção de empates. Tamanho de efeito ε² = H/(n−1), de 0 a 1 (Tomczak &
    Tomczak, 2014). ``None`` com menos de dois grupos não vazios ou poucos dados.
    """
    groups = [[v for v in g if v is not None] for g in groups]
    groups = [g for g in groups if g]
    k = len(groups)
    if k < 2:
        return None
    flat = [v for g in groups for v in g]
    n = len(flat)
    if n < 3:
        return None
    ranks, tie_term = _avg_ranks(flat)
    idx = 0
    h = 0.0
    for g in groups:
        rs = sum(ranks[idx:idx + len(g)])
        h += rs * rs / len(g)
        idx += len(g)
    h = 12.0 / (n * (n + 1)) * h - 3.0 * (n + 1)
    correction = 1.0 - tie_term / (n ** 3 - n) if n > 1 else 1.0
    if correction <= 0:
        return None
    h /= correction
    eps2 = max(0.0, min(1.0, h / (n - 1))) if n > 1 else None
    return {"h": h, "p": chi2_sf(h, k - 1), "df": k - 1, "epsilon_sq": eps2, "k": k, "n": n}


# ------------------------------------------------- análise de sobrevivência

def kaplan_meier(observations, z=Z95):
    """Estimador de Kaplan–Meier (1958) da função de sobrevivência S(t).

    ``observations``: lista de ``(tempo, evento)``. ``evento`` é verdadeiro quando o desfecho
    ocorreu no tempo (ex.: abandono) e falso quando a observação é censurada (ainda na escola,
    transferido ou concluído — saiu sem ter o desfecho). Responde "qual a probabilidade de o
    estudante ainda estar na escola depois de t anos", sem supor forma de distribuição e usando
    quem saiu sem desfecho até onde foi observado (Kaplan & Meier, 1958, JASA 53(282), 457–481).

    Devolve os degraus da curva (tempo, em risco, eventos, S(t)) com IC 95% de Greenwood na escala
    log-log (fica em 0..1), o tempo mediano de sobrevivência (ou ``None`` se a curva não chega a
    0,5) e o total de eventos. ``None`` sem observações.
    """
    obs = [(t, bool(e)) for t, e in observations if t is not None and t >= 0]
    if not obs:
        return None
    n = len(obs)
    event_times = sorted({t for t, e in obs if e})
    s = 1.0
    greenwood = 0.0  # Σ d / (n·(n−d))
    steps = [{"t": 0, "n_risk": n, "events": 0, "survival": 1.0, "low": 1.0, "high": 1.0}]
    median = None
    for t in event_times:
        n_risk = sum(1 for tt, _ in obs if tt >= t)
        d = sum(1 for tt, e in obs if tt == t and e)
        if n_risk == 0:
            continue
        s *= 1.0 - d / n_risk
        if n_risk > d:
            greenwood += d / (n_risk * (n_risk - d))
        if 0.0 < s < 1.0:
            se_ll = math.sqrt(greenwood) / abs(math.log(s))  # IC log-log
            low = s ** math.exp(z * se_ll)
            high = s ** math.exp(-z * se_ll)
        else:
            low = high = s
        steps.append({"t": t, "n_risk": n_risk, "events": d, "survival": s,
                      "low": max(0.0, low), "high": min(1.0, high)})
        if median is None and s <= 0.5:
            median = t
    return {"steps": steps, "median": median, "events": sum(1 for _, e in obs if e), "n": n}


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


# ---------------------------------------------------------------- concordância entre avaliadores

def _agreement_weights(categories):
    """Pesos de concordância quadráticos: 1 na diagonal, caindo com o quadrado da distância ordinal (Cohen, 1968,
    Psychological Bulletin 70(4), 213–220, doi:10.1037/h0026256). Níveis vizinhos ainda contam como concordância
    parcial; níveis distantes, quase nada. Com uma única categoria, tudo concorda."""
    lo, hi = min(categories), max(categories)
    rng = hi - lo
    if not rng:
        return lambda a, b: 1.0
    return lambda a, b: 1.0 - ((a - b) / rng) ** 2


def percent_agreement(pairs):
    """Concordância bruta de pares ordinais (a, b): fração no MESMO nível e fração dentro de 1 nível."""
    n = len(pairs)
    if not n:
        return None
    exact = sum(1 for a, b in pairs if a == b) / n
    within1 = sum(1 for a, b in pairs if abs(a - b) <= 1) / n
    return {"exact": exact, "within1": within1, "pairs": n}


def _prevalence(pairs, categories):
    """Prevalência geral de cada categoria nas duas posições dos pares (marginal simétrica, pois a concordância
    entre dois avaliadores não tem posição privilegiada)."""
    counts = {c: 0 for c in categories}
    for a, b in pairs:
        counts[a] += 1
        counts[b] += 1
    total = 2 * len(pairs)
    return {c: counts[c] / total for c in categories} if total else None


def weighted_kappa(pairs, categories, weight=None):
    """Kappa ponderado quadrático (Cohen, 1968) para pares ordinais (a, b), tratados como não ordenados: a
    concordância esperada usa a mesma marginal nas duas posições. None quando indefinido (um único nível em tudo:
    a concordância esperada já é 1)."""
    n = len(pairs)
    if not n:
        return None
    w = weight or _agreement_weights(categories)
    pi = _prevalence(pairs, categories)
    po = sum(w(a, b) for a, b in pairs) / n
    pe = sum(w(i, j) * pi[i] * pi[j] for i in categories for j in categories)
    if pe >= 1:
        return None
    return (po - pe) / (1 - pe)


def gwet_ac2(pairs, categories, weight=None):
    """AC2 de Gwet (Gwet, 2008, British Journal of Mathematical and Statistical Psychology 61(1), 29–48,
    doi:10.1348/000711006X126600), a versão ponderada do AC1. Robusto ao "paradoxo do kappa": quando quase tudo
    cai num nível só, o kappa despenca mesmo com concordância alta; o AC2, não. Mostre os dois lado a lado."""
    n = len(pairs)
    if not n:
        return None
    q = len(categories)
    if q < 2:
        return None
    w = weight or _agreement_weights(categories)
    pi = _prevalence(pairs, categories)
    po = sum(w(a, b) for a, b in pairs) / n
    tw = sum(w(i, j) for i in categories for j in categories)
    pe = tw / (q * (q - 1)) * sum(pi[c] * (1 - pi[c]) for c in categories)
    if pe >= 1:
        return None
    return (po - pe) / (1 - pe)


def agreement_label(value):
    """Banda convencional de Landis & Koch (1977, Biometrics 33(1), 159–174) para kappa/AC: só referência."""
    if value is None:
        return None
    if value < 0.0:
        return "pior que o acaso"
    if value < 0.20:
        return "ligeira"
    if value < 0.40:
        return "razoável"
    if value < 0.60:
        return "moderada"
    if value < 0.80:
        return "substancial"
    return "quase perfeita"
