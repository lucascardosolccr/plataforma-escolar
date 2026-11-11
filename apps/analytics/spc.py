"""Frequência semana a semana com controle estatístico de processo.

Pergunta: a frequência desta semana caiu de verdade, ou é a oscilação de sempre? Reagir a cada semana ruim gera
trabalho e alarme à toa; ignorar uma mudança real atrasa a ação. O controle estatístico de processo separa
variação comum de causa especial (Shewhart; aplicado à melhoria educacional em Bryk et al., 2015, *Learning to
Improve*, Harvard Education Press).

- **Carta p′ de Laney** (2002, Quality Engineering 14(4), 531–537): limites a 3 desvios da presença média, com o
  desvio binomial multiplicado por σz, a dispersão real entre semanas. Com milhares de registros por semana, a carta
  p comum teria limites estreitos demais e acusaria toda semana.
- **Regras de Anhøj** (Anhøj & Olesen, 2014, PLoS ONE 9(11): e113825): sequência do mesmo lado da mediana maior que
  log2(n) + 3 (mudança de patamar) e cruzamentos abaixo do 5º percentil binomial. Alarme falso perto de 5% qualquer
  que seja o número de semanas.
- Só tira conclusão com ``MIN_WEEKS`` semanas ou mais. Semana sem chamada não entra.
- Semana com menos de ``MIN_SHARE`` dos registros de uma semana típica (mediana) fica fora da carta e é listada à
  parte: quase sempre é chamada não lançada ou semana de feriado, e um ponto com 1 registro (0% ou 100%) não diz
  nada sobre a frequência. A carta compara só semanas comparáveis.
"""

import datetime
from collections import defaultdict
from statistics import median

from apps.core.stats import anhoej, laney_p
from apps.pedagogy.models import AttendanceRecord

MIN_WEEKS = 8
MIN_SHARE = 0.25
PRESENCE = (AttendanceRecord.Status.PRESENT, AttendanceRecord.Status.LATE)


def weekly(school, start, end, class_group=None):
    qs = AttendanceRecord.objects.filter(school=school, date__gte=start, date__lte=end)
    if class_group is not None:
        qs = qs.filter(class_group=class_group)
    weeks = defaultdict(lambda: [0, 0])
    for d, st in qs.values_list("date", "status").iterator():
        monday = d - datetime.timedelta(days=d.weekday())
        weeks[monday][1] += 1
        if st in PRESENCE:
            weeks[monday][0] += 1
    return [(monday, k, n) for monday, (k, n) in sorted(weeks.items())]


def control(school, start, end, class_group=None):
    data = weekly(school, start, end, class_group)
    typical = median([n for _, _, n in data]) if data else 0
    sparse = [(m, k, n) for m, k, n in data if n < MIN_SHARE * typical]
    data = [row for row in data if row not in sparse]
    chart = laney_p([(m, k, n) for m, k, n in data])
    out = {"weeks": len(data), "enough": len(data) >= MIN_WEEKS, "chart": chart, "runs": None, "signals": [],
           "sparse": [{"label": m, "n": n} for m, _, n in sparse], "typical": typical}
    if not chart:
        return out
    if out["enough"]:
        out["runs"] = anhoej([p["p"] for p in chart["points"]])
        for p in chart["points"]:
            if p["signal"]:
                out["signals"].append(p)
    return out
