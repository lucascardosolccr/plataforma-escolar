"""Trajetória acadêmica e indicadores precoces de dificuldade, com métodos explícitos e conferíveis.

Pergunta: o estudante está melhorando, estável ou em queda? Desde quando? E quais sinais, de acordo com a
pesquisa sobre sistemas de alerta precoce, pedem uma conversa agora, antes do fim do bimestre?

Métodos (Python puro, sem dependência nova):

- **Tendência robusta** pela inclinação de Theil–Sen: mediana das inclinações entre todos os pares de pontos
  (Sen, 1968, JASA 63(324), 1379–1389, doi:10.2307/2285891). Uma nota atípica não puxa a reta, como
  aconteceria nos mínimos quadrados.
- **A tendência é real?** Teste de Mann–Kendall (Mann, 1945, Econometrica 13(3), 245–259,
  doi:10.2307/1907187), com correção para empates e aproximação normal. Só afirma tendência com p < 0,10 e
  variação de pelo menos 0,2 ponto (na escala de 0 a 10) a cada 30 dias.
- **Mínimo de pontos:** ``MIN_POINTS`` (6). Linhas de tendência com poucos pontos são instáveis. Na
  monitoração do progresso da leitura, a decisão só ficou suficiente com 14 medidas e dados de boa
  qualidade (Christ, Zopluoglu, Long & Monaghen, 2012, Exceptional Children 78(3), 356–373,
  doi:10.1177/001440291207800306). Com 6 a 13 pontos, a tela avisa que a tendência é preliminar.
- **Quando começou a queda:** CUSUM unilateral (Page, 1954, Biometrika 41(1/2), 100–115,
  doi:10.1093/biomet/41.1-2.100), com referência na primeira metade da série do próprio estudante,
  k = 0,5 e h = 4 desvios. Detecta uma mudança persistente antes que a média do período a revele. Para
  não confundir oscilação com queda, o desvio tem piso (0,05 nas notas; 0,10 na presença semanal, em que
  uma falta numa semana de 5 aulas já vale 0,20) e a média depois do início precisa ficar ao menos 0,10
  abaixo da referência (1 ponto em 10, ou 10 pontos percentuais de presença).
- **Muitas disciplinas, muitos testes:** a queda numa disciplina só entra no indicador com a correção de
  Bonferroni pelo número de disciplinas testadas (Dunn, 1961, JASA 56(293), 52–64,
  doi:10.1080/01621459.1961.10482090). Na tela, cada disciplina mostra a própria tendência.
- **Dupla discrepância:** nível abaixo do quartil inferior da turma e ritmo de evolução abaixo da mediana
  da turma ao mesmo tempo. Responder pouco à aula, e não só ter nota baixa, é o critério mais informativo
  para decidir apoio (Fuchs, 2003, Learning Disabilities Research & Practice 18(3), 172–186,
  doi:10.1111/1540-5826.00073). Só com ``MIN_PEERS`` colegas com tendência calculada.

Indicadores precoces, todos com regra explícita e nenhuma pontuação:

- **Frequência:** presença abaixo de 90% das aulas registradas, ou seja, ausência crônica (Balfanz &
  Byrnes, 2012, *The Importance of Being in School*, Johns Hopkins). Abaixo de 75% é o limite legal
  (LDB, art. 24, VI).
- **Comportamento:** 2 ou mais ocorrências no período.
- **Desempenho:** alguma disciplina abaixo da média de aprovação. Com a frequência e o comportamento, forma
  o trio "ABC", que no 6º ano sinalizou cerca de 60% dos que não concluiriam o ensino médio (Balfanz,
  Herzog & Mac Iver, 2007, Educational Psychologist 42(4), 223–235, doi:10.1080/00461520701621079).
  Reprovações e frequência do primeiro ano do ensino médio foram os preditores mais fortes de conclusão em
  Chicago (Allensworth & Easton, 2007, Consortium on Chicago School Research).
- **Entregas:** menos de 60% das atividades registradas entregues (com pelo menos 3).
- **Trajetória:** queda confirmada pelo Mann–Kendall ou mudança detectada pelo CUSUM, nas notas ou na
  frequência semanal.
- **Dupla discrepância** (acima).

Limites: indicadores sinalizam e muitos sinalizados não chegam ao desfecho, enquanto parte dos que chegam
não é sinalizada (Bowers, Sprott & Taff, 2013, The High School Journal 96(2), 77–100). Por isso a escola
valida os indicadores com os próprios dados (``ews_validation.py``) antes de confiar neles. Nada aqui usa
dado de inclusão, saúde, cor, renda ou família.
"""

import math
import statistics
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

MIN_POINTS = 6
SOLID_POINTS = 14
MK_ALPHA = 0.10
MIN_CHANGE_30D = 0.02  # 0,2 ponto na escala de 0 a 10, a cada 30 dias
OSCILLATION = 0.18  # dispersão robusta dos resíduos (fração da nota máxima)
CUSUM_K, CUSUM_H = 0.5, 4.0
MIN_SIGMA, MIN_SIGMA_ATT = 0.05, 0.10
MIN_SHIFT = 0.10
CHRONIC, LEGAL_MIN = 0.90, 0.75
MIN_ATT_RECORDS = 10
MIN_PEERS = 5
MAX_PROJECTION_DAYS = 60  # projetar além disso com poucas notas é extrapolação, não tendência
OCCURRENCES = 2
MIN_DELIVERY, MIN_REGISTERED = 0.60, 3

INDICATORS = {
    "frequencia": "Frequência",
    "comportamento": "Comportamento",
    "desempenho": "Desempenho",
    "entregas": "Entregas",
    "trajetoria": "Trajetória em queda",
    "dupla_discrepancia": "Nível e ritmo abaixo da turma",
}
TRENDS = {
    "melhora": ("Melhora", "↗"),
    "estavel": ("Estável", "→"),
    "queda": ("Queda", "↘"),
    "oscilante": ("Oscilante", "↕"),
    "insuficiente": ("Dados insuficientes", "·"),
}


# --------------------------------------------------------------------------- estatística


def _median(values):
    return statistics.median(values) if values else None


def theil_sen(xs, ys):
    """(inclinação, intercepto): mediana das inclinações entre pares; intercepto = mediana de y − b·x."""
    slopes = [(ys[j] - ys[i]) / (xs[j] - xs[i]) for i in range(len(xs)) for j in range(i + 1, len(xs))
              if xs[j] != xs[i]]
    if not slopes:
        return 0.0, _median(ys) or 0.0
    b = statistics.median(slopes)
    return b, statistics.median([y - b * x for x, y in zip(xs, ys)])


def mann_kendall(ys):
    """(S, z, p bicaudal) com correção de empates (variância de Kendall) e de continuidade."""
    n = len(ys)
    s = sum((ys[j] > ys[i]) - (ys[j] < ys[i]) for i in range(n) for j in range(i + 1, n))
    ties = [c for c in _counts(ys) if c > 1]
    var = (n * (n - 1) * (2 * n + 5) - sum(t * (t - 1) * (2 * t + 5) for t in ties)) / 18
    if var <= 0:
        return s, 0.0, 1.0
    z = (s - 1) / math.sqrt(var) if s > 0 else (s + 1) / math.sqrt(var) if s < 0 else 0.0
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return s, z, p


def _counts(values):
    c = defaultdict(int)
    for v in values:
        c[round(v, 6)] += 1
    return list(c.values())


def cusum_drop(ys, min_sigma=MIN_SIGMA, min_shift=MIN_SHIFT):
    """Índice em que começou a queda que AINDA está em curso (CUSUM inferior), ou None.

    Referência: média e desvio da primeira metade da série (no mínimo 3 pontos). O desvio tem piso
    ``min_sigma`` para que um início sem variação não transforme qualquer oscilação em alarme. A queda só
    vale se a soma não voltou a zero até o último ponto, se a média a partir do início ficou ``min_shift``
    abaixo da referência e se os dois últimos resultados continuam abaixo dela (uma prova ruim seguida de
    recuperação não é queda em curso)."""
    n = len(ys)
    if n < MIN_POINTS:
        return None
    base = ys[:max(3, n // 2)]
    mu, sd = statistics.fmean(base), max(statistics.pstdev(base), min_sigma)
    s, start, alarm = 0.0, None, None
    for i, y in enumerate(ys):
        new = min(0.0, s + (y - mu) / sd + CUSUM_K)
        if s == 0.0 and new < 0.0:
            start = i
        if new == 0.0:
            start = alarm = None  # recuperou: a queda anterior não está mais em curso
        s = new
        if s <= -CUSUM_H and alarm is None:
            alarm = start if start is not None else i
    if (alarm is not None and s < 0.0 and mu - statistics.fmean(ys[alarm:]) >= min_shift
            and mu - statistics.fmean(ys[-2:]) >= min_shift):
        return alarm
    return None


def analyse(points, horizon=None, min_sigma=MIN_SIGMA):
    """Tendência de uma série [(data, valor de 0 a 1)], em ordem de data.

    Devolve estado, inclinação a cada 30 dias, p do Mann–Kendall, nível recente, início da queda
    (CUSUM) e, se houver tendência, a projeção até ``horizon`` (fim do período), limitada a
    ``MAX_PROJECTION_DAYS`` depois do último resultado, com faixa de ±2 desvios robustos."""
    points = sorted(points)
    n = len(points)
    out = {"n": n, "points": points, "trend": "insuficiente", "preliminary": n < SOLID_POINTS,
           "level": round(statistics.fmean([v for _, v in points[-3:]]), 3) if points else None}
    if n < MIN_POINTS:
        return out
    d0 = points[0][0]
    xs = [(d - d0).days for d, _ in points]
    ys = [v for _, v in points]
    b, a = theil_sen(xs, ys)
    _, z, p = mann_kendall(ys)
    resid = [y - (a + b * x) for x, y in zip(xs, ys)]
    med = statistics.median(resid)
    spread = 1.4826 * statistics.median([abs(r - med) for r in resid])
    slope30 = b * 30
    if p < MK_ALPHA and slope30 <= -MIN_CHANGE_30D:
        trend = "queda"
    elif p < MK_ALPHA and slope30 >= MIN_CHANGE_30D:
        trend = "melhora"
    elif spread >= OSCILLATION:
        trend = "oscilante"
    else:
        trend = "estavel"
    drop = cusum_drop(ys, min_sigma)
    out.update(trend=trend, slope30=round(slope30, 4), p=round(p, 4), z=round(z, 3), spread=round(spread, 3),
               line=(d0, a, b), drop_on=points[drop][0] if drop is not None else None)
    if horizon:
        horizon = min(horizon, points[-1][0] + timedelta(days=MAX_PROJECTION_DAYS))
    if horizon and trend in ("queda", "melhora") and horizon > points[-1][0]:
        y_end = a + b * (horizon - d0).days
        band = 2 * max(spread, MIN_SIGMA)  # nunca largura zero: série curta e "perfeita" não é certeza
        out["projection"] = {"date": horizon, "value": round(min(max(y_end, 0.0), 1.0), 3),
                             "low": round(min(max(y_end - band, 0.0), 1.0), 3),
                             "high": round(min(max(y_end + band, 0.0), 1.0), 3)}
    return out


def quantile(values, q):
    """Quantil por interpolação linear (método 7 de Hyndman & Fan, o padrão do R)."""
    v = sorted(values)
    if not v:
        return None
    pos = (len(v) - 1) * q
    lo = math.floor(pos)
    return v[lo] + (v[min(lo + 1, len(v) - 1)] - v[lo]) * (pos - lo)


def auc(scores_pos, scores_neg):
    """Área sob a curva ROC pela estatística de Mann–Whitney (empates valem meio)."""
    if not scores_pos or not scores_neg:
        return None
    wins = 0.0
    for p in scores_pos:
        for q in scores_neg:
            wins += 1.0 if p > q else 0.5 if p == q else 0.0
    return wins / (len(scores_pos) * len(scores_neg))


# --------------------------------------------------------------------------- resposta à intervenção

MIN_SIDE = 3
RESPONSE_WINDOW = 120


def segment_change(points, cut):
    """Antes × depois de uma data: nível médio e ritmo (Theil–Sen a cada 30 dias) de cada lado.

    É a leitura da série temporal interrompida (Wagner, Soumerai, Zhang & Ross-Degnan, 2002, J Clin Pharm Ther
    27(4), 299–309, doi:10.1046/j.1365-2710.2002.00430.x), com estimador robusto em vez de mínimos quadrados.
    Precisa de ``MIN_SIDE`` resultados de cada lado."""
    before = sorted(p for p in points if p[0] < cut)
    after = sorted(p for p in points if p[0] >= cut)
    out = {"n_before": len(before), "n_after": len(after), "ok": len(before) >= MIN_SIDE and len(after) >= MIN_SIDE}
    if not out["ok"]:
        return out

    def rate(seg):
        return theil_sen([(d - seg[0][0]).days for d, _ in seg], [v for _, v in seg])[0] * 30

    mb, ma = statistics.fmean(v for _, v in before), statistics.fmean(v for _, v in after)
    change = ma - mb
    out.update(mean_before=round(mb, 3), mean_after=round(ma, 3), change=round(change, 3),
               slope_before=round(rate(before), 4), slope_after=round(rate(after), 4),
               label="subiu" if change >= MIN_SHIFT else "caiu" if change <= -MIN_SHIFT else "sem mudança clara")
    return out


def intervention_response(iv, today=None):
    """Notas da disciplina da intervenção antes e depois do início, para cada estudante atendido, e a mesma
    variação média dos colegas da turma que não estavam nela, como referência.

    A referência existe por causa da regressão à média: quem é escolhido para apoio por estar com nota baixa
    tende a melhorar um pouco mesmo sem apoio (Barnett, van der Pols & Dobson, 2005, Int J Epidemiol 34(1),
    215–220, doi:10.1093/ije/dyh299). Mesmo assim, é associação no tempo, não prova de efeito."""
    from apps.analytics import bi
    from apps.registry.models import Enrollment

    today = today or timezone.localdate()
    start = iv.starts_on - timedelta(days=RESPONSE_WINDOW)
    rules, _ = bi.school_rules(iv.school)
    top = _top(rules.get(iv.subject_id))
    targets = {s.pk: s for s in iv.students.all()}
    members = set(Enrollment.objects.filter(class_group=iv.class_group, status="ativo")
                  .values_list("student_id", flat=True))
    grades = bi.load_grades_light(members | set(targets), start, today, class_group=iv.class_group,
                                  subject_ids=[iv.subject_id])

    def series(sid):
        return [(g.evaluation.date, min(max(float(g.value) / top, 0.0), 1.0)) for g in grades.get(sid, [])]

    peers = [c for c in (segment_change(series(sid), iv.starts_on) for sid in members - set(targets)) if c["ok"]]
    ref = statistics.fmean(c["change"] for c in peers) if len(peers) >= MIN_PEERS else None
    from apps.core.fmt import dec

    def ten(v, signed=False):  # na escala de 0 a 10, com vírgula
        if v is None:
            return "—"
        text = dec(abs(v) * 10 if signed else v * 10, 1)
        return ("+" if v > 0 else "−" if v < 0 else "") + text if signed else text

    rows = []
    for sid, st in sorted(targets.items(), key=lambda kv: kv[1].full_name):
        c = segment_change(series(sid), iv.starts_on)
        if c["ok"]:
            if ref is not None:
                c["vs_peers"] = round(c["change"] - ref, 3)
            c["show"] = {"before": ten(c["mean_before"]), "after": ten(c["mean_after"]),
                         "change": ten(c["change"], True), "slope_before": ten(c["slope_before"], True),
                         "slope_after": ten(c["slope_after"], True), "vs_peers": ten(c.get("vs_peers"), True)}
        rows.append({"student": st, **c})
    return {"rows": rows, "peers": len(peers), "reference": round(ref, 3) if ref is not None else None,
            "reference_show": ten(ref, True) if ref is not None else None, "start": start, "cut": iv.starts_on,
            "min_side": MIN_SIDE, "min_peers": MIN_PEERS}


# --------------------------------------------------------------------------- dados da turma


def _weekly_presence(records):
    """[(segunda-feira, taxa de presença)] das semanas com pelo menos 2 registros."""
    from apps.analytics.bi import PRESENCE

    weeks = defaultdict(lambda: [0, 0])
    for d, status in records:
        w = d - timedelta(days=d.weekday())
        weeks[w][1] += 1
        weeks[w][0] += status in PRESENCE
    return [(w, ok / total) for w, (ok, total) in sorted(weeks.items()) if total >= 2]


def _top(rule):
    passing = rule.passing_grade if rule else 6
    return 10.0 if float(passing) <= 10 else 100.0


def thresholds_for(school):
    """Limiares dos indicadores configurados pela escola (escala do EIA), em proporção."""
    from .models import MasteryScale

    scale = MasteryScale.for_school(school)
    return {"attendance": float(scale.ews_attendance) / 100, "delivery": float(scale.ews_delivery) / 100,
            "occurrences": scale.ews_occurrences}


DEFAULT_THRESHOLDS = {"attendance": CHRONIC, "delivery": MIN_DELIVERY, "occurrences": OCCURRENCES}


def class_overview(class_group, start, end, today=None, *, behavior=True, students=None, rules=None,
                   subject_ids=None, thresholds=None):
    """Trajetória e indicadores de cada estudante da turma entre ``start`` e ``end``.

    ``students``: ids a considerar (padrão: matrícula ativa). A validação retrospectiva passa quem estava
    na turma na data de corte. ``behavior=False`` deixa as ocorrências de fora, para quem não pode vê-las.
    ``subject_ids``: só as notas dessas disciplinas (o professor vê as próprias)."""
    from apps.analytics import bi
    from apps.pedagogy.models import Activity, Occurrence, Submission
    from apps.registry.models import Enrollment, Student

    today = today or timezone.localdate()
    horizon = end  # a projeção mira o fim do período escolhido; os dados param em hoje
    end = min(end, today)
    rules, _limit = rules or bi.school_rules(class_group.school)
    if students is None:
        students = set(Enrollment.objects.filter(class_group=class_group, status="ativo")
                       .values_list("student_id", flat=True))
    ids = sorted(students)
    people = {s.pk: s for s in Student.objects.filter(pk__in=ids)}
    grades = bi.load_grades_light(ids, start, end, class_group=class_group, subject_ids=subject_ids)
    records = bi.load_attendance(ids, start, end, class_group=class_group)
    acts = [a for a in Activity.objects.filter(class_group=class_group, status="publicada", deadline__gte=start,
                                               deadline__lte=end, deadline__lt=today).only("pk", "deadline")]
    subs = defaultdict(dict)
    for s in Submission.objects.filter(activity__in=acts, student_id__in=ids).only("activity_id", "student_id",
                                                                                     "status"):
        subs[s.student_id][s.activity_id] = s.status
    occ = defaultdict(int)
    if behavior:
        for sid in Occurrence.objects.filter(student_id__in=ids, date__gte=start, date__lte=end) \
                .values_list("student_id", flat=True):
            occ[sid] += 1
    rows, subjects = [], {}
    for sid in ids:
        if sid not in people:
            continue
        g = grades.get(sid, [])
        per_subject = defaultdict(list)
        overall = []
        for x in g:
            subj = x.evaluation.subject
            subjects[subj.pk] = subj
            v = min(max(float(x.value) / _top(rules.get(subj.pk)), 0.0), 1.0)
            per_subject[subj.pk].append((x.evaluation.date, v))
            overall.append((x.evaluation.date, v))
        averages = bi._subject_rows(g, rules)
        att = records.get(sid, [])
        from apps.analytics.bi import PRESENCE

        presence = (sum(1 for _, s in att if s in PRESENCE) / len(att)) if att else None
        st = subs.get(sid, {})
        delivered = sum(1 for v in st.values() if v in Submission.DELIVERED_STATUSES)
        row = {
            "student": people[sid], "overall": analyse(overall, horizon),
            "subjects": {pk: {**analyse(pts, horizon), "subject": subjects[pk],
                              "average": averages.get(pk, {}).get("average"),
                              "below": averages.get(pk, {}).get("below", False)}
                         for pk, pts in per_subject.items()},
            "attendance": {**analyse(_weekly_presence(att), min_sigma=MIN_SIGMA_ATT), "rate": presence,
                           "records": len(att)},
            "delivery": {"delivered": delivered, "registered": len(st),
                         "rate": delivered / len(st) if st else None},
            "occurrences": occ.get(sid, 0) if behavior else None,
        }
        rows.append(row)
    _dual_discrepancy(rows)
    th = thresholds or thresholds_for(class_group.school)
    for row in rows:
        row["indicators"] = indicators(row, th)
    return {"rows": rows, "subjects": sorted(subjects.values(), key=lambda s: s.name), "start": start, "end": end,
            "behavior": behavior, "thresholds": th}


def _dual_discrepancy(rows):
    """Marca quem está no quartil inferior de nível E abaixo da mediana de ritmo na série geral."""
    ok = [r for r in rows if r["overall"]["trend"] != "insuficiente"]
    for r in rows:
        r["dual"] = None
    if len(ok) < MIN_PEERS:
        return
    p25 = quantile([r["overall"]["level"] for r in ok], 0.25)
    med = quantile([r["overall"]["slope30"] for r in ok], 0.5)
    for r in ok:
        r["dual"] = {"flag": r["overall"]["level"] <= p25 and r["overall"]["slope30"] < med,
                     "p25": p25, "median_slope": med, "peers": len(ok)}


def indicators(row, thresholds=None):
    """[{chave, rótulo, detalhe, nível}] na ordem de INDICATORS. Só os que se aplicam."""
    th = thresholds or DEFAULT_THRESHOLDS
    out = []
    att = row["attendance"]
    if att["rate"] is not None and att["records"] >= MIN_ATT_RECORDS and att["rate"] < th["attendance"]:
        legal = att["rate"] < LEGAL_MIN
        out.append({"key": "frequencia", "level": "importante" if legal else "atencao",
                    "detail": f"Presença de {round(att['rate'] * 100)}% em {att['records']} aulas registradas"
                              + (" (abaixo do mínimo legal de 75%)." if legal else
                                 f" (abaixo de {round(th['attendance'] * 100)}%, o limiar da escola).")})
    if row["occurrences"] is not None and row["occurrences"] >= th["occurrences"]:
        out.append({"key": "comportamento", "level": "atencao",
                    "detail": f"{row['occurrences']} ocorrências registradas no período."})
    below = [s for s in row["subjects"].values() if s["below"]]
    if below:
        out.append({"key": "desempenho", "level": "importante" if len(below) >= 2 else "atencao",
                    "detail": "Abaixo da média em " + ", ".join(sorted(s["subject"].name for s in below)) + "."})
    d = row["delivery"]
    if d["rate"] is not None and d["registered"] >= MIN_REGISTERED and d["rate"] < th["delivery"]:
        out.append({"key": "entregas", "level": "atencao",
                    "detail": f"{d['delivered']} de {d['registered']} atividades entregues."})
    tested = [s for s in row["subjects"].values() if s["trend"] != "insuficiente"]
    alpha = MK_ALPHA / max(len(tested), 1)  # Bonferroni pelo número de disciplinas testadas
    # O CUSUM por disciplina (poucas notas) fica só na tela; no indicador, a queda confirmada e corrigida.
    falling = [s["subject"].name for s in tested if s["trend"] == "queda" and s["p"] < alpha]
    parts = []
    if row["overall"]["trend"] == "queda" or row["overall"].get("drop_on"):
        when = row["overall"].get("drop_on")
        parts.append("notas em queda" + (f" desde {when:%d/%m}" if when else ""))
    if falling:
        parts.append("queda em " + ", ".join(sorted(set(falling))))
    if att["trend"] == "queda" or att.get("drop_on"):
        when = att.get("drop_on")
        parts.append("frequência semanal caindo" + (f" desde {when:%d/%m}" if when else ""))
    if parts:
        text = "; ".join(parts)
        out.append({"key": "trajetoria", "level": "atencao", "detail": text[0].upper() + text[1:] + "."})
    if row.get("dual") and row["dual"]["flag"]:
        out.append({"key": "dupla_discrepancia", "level": "atencao",
                    "detail": f"Nível no quartil inferior e ritmo abaixo da mediana de {row['dual']['peers']} "
                              "colegas com dados suficientes."})
    for i in out:
        i["label"] = INDICATORS[i["key"]]
    return out
