"""Diagnóstico da trajetória: o que os anos anteriores dizem sobre o estudante, com regra e fonte explícitas.

Cada achado traz a evidência (os números do próprio estudante), a regra que o acendeu, a referência e uma
sugestão de ação. Não há pontuação nem classificação do estudante: são sinais para conversa e planejamento, e o
diagnóstico também mostra o que vai bem.

Sinais e fundamentos:

- **Retenção anterior.** Entre os preditores de abandono revistos em 17 estudos, a retenção aparece entre os
  mais fortes (Jimerson, Anderson & Whipple, 2002, Psychology in the Schools 39(4), 441–457,
  doi:10.1002/pits.10046).
- **Distorção idade-série** de 2 anos ou mais (definição do INEP; idade de referência pela Resolução CNE/CEB
  nº 2/2018).
- **Ausência crônica:** presença abaixo de 90% num ano (Balfanz & Byrnes, 2012, *The Importance of Being in
  School*, Johns Hopkins). Mais grave quando se repete em anos seguidos.
- **Dificuldade persistente:** o mesmo componente abaixo da média de aprovação em 2 ou mais anos seguidos. As
  notas dadas pelo professor, ano a ano, preveem a conclusão da escolaridade melhor do que muitos indicadores
  isolados, e a média do ano (não a acumulada) é o melhor sinal (Bowers, 2010, Journal of Educational Research
  103(3), 191–207, doi:10.1080/00220670903382970). Notas misturam aprendizagem com engajamento e conduta
  (Brookhart et al., 2016, Review of Educational Research 86(4), 803–848, doi:10.3102/0034654316672069), e por
  isso o diagnóstico fala em "sinal", nunca em "nível de aprendizagem".
- **Queda entre anos:** média geral 1 ponto ou mais abaixo da do ano anterior. Quando o ano anterior foi
  excepcionalmente alto, parte da queda é regressão à média (Barnett, van der Pols & Dobson, 2005, International
  Journal of Epidemiology 34(1), 215–220, doi:10.1093/ije/dyh299), e a tela avisa. Com o percentil na turma, a
  queda só conta se ele também cair (descontando a mudança de professor e de critério de um ano para outro).
- **Tendência de vários anos:** Theil–Sen e Mann–Kendall (os mesmos de ``cognitio.trajectory``) com 3 ou mais
  anos; com menos de 6 pontos o teste tem pouco poder, então a tendência aparece como descritiva.
- **Mudanças de escola** fora da passagem de etapa: 2 ou mais (Rumberger, 2003, Journal of Negro Education
  72(1), 6–21). Mudança no 5º→6º ano e no 9º ano→médio é estrutural e não conta.
- **Transição de etapa:** 6º ano e 1ª série do médio costumam ter queda de desempenho (Alspaugh, 1998, Journal
  of Educational Research 92(1), 20–25). Sinal de contexto, para acolhimento.
- **Ano atual abaixo do próprio histórico:** média parcial do ano 1 ponto ou mais abaixo da média dos anos
  anteriores do próprio estudante (comparação com ele mesmo, não com a turma).

Nada aqui usa dado de inclusão, saúde, cor, renda ou família.
"""

from dataclasses import dataclass, field
from statistics import mean

from apps.cognitio.trajectory import mann_kendall, theil_sen
from apps.core.fmt import dec

from . import stages as st

DROP = 1.0
PERCENTILE_DROP = 20
HIGH_PREVIOUS = 75  # percentil: ano anterior "excepcionalmente alto" para o aviso de regressão à média
MIN_YEARS_TREND = 3
MK_ALPHA = 0.10
MIN_SLOPE = 0.3  # ponto por ano
MOBILITY = 2
SPREAD = 3  # componentes com dificuldade persistente a partir dos quais o sinal vira geral

REF = {
    "retencao": "Jimerson, Anderson & Whipple (2002)",
    "distorcao": "INEP, taxa de distorção idade-série; Resolução CNE/CEB nº 2/2018",
    "frequencia": "Balfanz & Byrnes (2012)",
    "persistente": "Bowers (2010); Brookhart et al. (2016)",
    "queda": "Bowers (2010); Barnett, van der Pols & Dobson (2005)",
    "tendencia": "Sen (1968); Mann (1945)",
    "mobilidade": "Rumberger (2003)",
    "transicao": "Alspaugh (1998)",
    "proprio": "Comparação com o próprio histórico",
    "dados": "Qualidade dos dados",
}


@dataclass
class Finding:
    key: str
    title: str
    level: str  # "atencao", "observar", "positivo", "dados"
    evidence: str
    rule: str
    action: str = ""
    ref: str = ""
    years: list = field(default_factory=list)

    @property
    def level_label(self):
        return {"atencao": "Pede atenção", "observar": "Observar", "positivo": "Ponto forte",
                "dados": "Dados"}[self.level]


def _years(rows):
    return ", ".join(str(r["year"]) for r in rows)


def diagnose(rows):
    """Lista de achados, os que pedem atenção primeiro."""
    done = [r for r in rows if not r["in_progress"]]
    current = next((r for r in reversed(rows) if r["in_progress"]), None)
    found = []

    retained = [r for r in rows if r["retained"]]
    if retained:
        official = all(r["basis"] == "oficial" for r in retained)
        found.append(Finding(
            "retencao", "Retenção em ano anterior", "atencao",
            f"{len(retained)} retenção(ões): {_years(retained)}"
            + ("" if official else " (há retenção deduzida por repetir a série; confira com o histórico)") + ".",
            "Uma ou mais retenções registradas ou deduzidas.",
            "Plano de acompanhamento desde o início do ano, com metas curtas e conversa com a família. Uma nova "
            "retenção sem plano de apoio tende a repetir o problema.", REF["retencao"], [r["year"] for r in retained]))

    last = rows[-1] if rows else None
    if last and last["distortion"] is not None and last["distortion"] >= st.DISTORTION_YEARS:
        found.append(Finding(
            "distorcao", "Distorção idade-série", "atencao",
            f"{last['age']} anos em 31/03/{last['year']} no {last['stage_label']} (esperado: {last['expected_age']}); "
            f"{last['distortion']} ano(s) acima.",
            "Idade 2 anos ou mais acima da esperada para a etapa.",
            "Verificar a política de correção de fluxo da rede (classes de aceleração, reforço) e o histórico de "
            "entradas tardias ou retenções.", REF["distorcao"], [last["year"]]))

    chronic = [r for r in done if r["chronic"]]
    if chronic:
        repeated = any(b["year"] == a["year"] + 1 for a, b in zip(chronic, chronic[1:]))
        found.append(Finding(
            "frequencia", "Ausência crônica" + (" repetida" if repeated else ""), "atencao",
            "Presença abaixo de 90% em " + "; ".join(f"{r['year']} ({dec(r['attendance'], 1)}%)" for r in chronic) + ".",
            "Presença anual abaixo de 90% das aulas.",
            "Entender as causas com a família (saúde, transporte, trabalho, vínculo com a escola) e acompanhar a "
            "frequência semanal desde o início do ano; considerar a busca ativa.", REF["frequencia"],
            [r["year"] for r in chronic]))
    if current and current["attendance"] is not None and current["attendance"] < 90 and \
            (current["attendance_records"] or 0) >= 10:
        found.append(Finding(
            "frequencia_atual", "Frequência baixa no ano atual", "atencao",
            f"{dec(current['attendance'], 1)}% de presença até agora em {current['year']}.",
            "Presença abaixo de 90% no ano em andamento (com 10 ou mais registros).",
            "Conversar com a família agora, antes do limite legal de 75%.", REF["frequencia"], [current["year"]]))

    by_key = {}
    for r in done:
        for s in r["subjects"]:
            if s["value"] is not None:
                by_key.setdefault(s["key"], {})[r["year"]] = s
    persistent = []
    for key, years in by_key.items():
        best, run, prev = [], [], None
        for y in sorted(years):
            if years[y]["below"]:
                run = run + [y] if run and prev == y - 1 else [y]
            else:
                run = []
            prev = y
            if len(run) > len(best):
                best = run[:]
        if len(best) >= 2:
            persistent.append((key, best, [years[y]["value"] for y in best]))
    if len(persistent) >= SPREAD:
        # Em quase todos os componentes: o sinal é geral (frequência, vínculo, alfabetização), não de um conteúdo.
        years = sorted({y for _, ys, _ in persistent for y in ys})
        found.append(Finding(
            "persistente_geral", f"Dificuldade persistente em {len(persistent)} componentes", "atencao",
            "Abaixo da média de aprovação em 2 ou mais anos seguidos em: "
            + "; ".join(f"{key} ({', '.join(dec(v, 1) for v in vals)})" for key, ys, vals in sorted(persistent)) + ".",
            f"O mesmo componente abaixo da média em 2 ou mais anos seguidos, em {SPREAD} ou mais componentes.",
            "Quando a dificuldade atravessa quase todos os componentes, a causa costuma ser comum a todos: leitura e "
            "escrita, frequência, vínculo com a escola ou uma necessidade ainda não identificada. Conversar com a família e "
            "avaliar a alfabetização antes de planejar reforço por componente.", REF["persistente"], years))
        persistent = []
    for key, ys, vals in sorted(persistent):
        found.append(Finding(
            "persistente", f"Dificuldade persistente em {key}", "atencao",
            f"Abaixo da média de aprovação em {len(ys)} anos seguidos ({', '.join(f'{y}: {dec(v, 1)}' for y, v in zip(ys, vals))}).",
            "O mesmo componente abaixo da média de aprovação em 2 ou mais anos seguidos.",
            "Retomar pré-requisitos do componente (Mapa de aprendizagem) e combinar apoio no contraturno. Dificuldade "
            "que atravessa anos raramente se resolve só com a aula regular.", REF["persistente"], ys))

    for prev, r in zip(done, done[1:]):
        if r["delta"] is None or r["delta"] > -DROP:
            continue
        pct_drop = (prev["percentile"] - r["percentile"]) if (prev["percentile"] is not None
                                                             and r["percentile"] is not None) else None
        if pct_drop is not None and pct_drop < PERCENTILE_DROP:
            continue  # a turma toda caiu junto: critério ou professor, não o estudante
        rtm = prev["percentile"] is not None and prev["percentile"] >= HIGH_PREVIOUS
        found.append(Finding(
            "queda", f"Queda de {prev['year']} para {r['year']}", "atencao" if r["delta"] <= -2 * DROP else "observar",
            f"Média geral de {dec(prev['average'], 1)} para {dec(r['average'], 1)}"
            + (f"; posição na turma do percentil {prev['percentile']} para {r['percentile']}" if pct_drop is not None else "")
            + "." + (" O ano anterior foi excepcionalmente alto: parte da queda pode ser regressão à média."
                     if rtm else ""),
            "Média geral 1 ponto ou mais abaixo da do ano anterior (e queda de 20+ no percentil, quando há turma).",
            "Ouvir o estudante: mudança de etapa, de escola, de rotina ou de vínculo costuma explicar quedas bruscas.",
            REF["queda"], [prev["year"], r["year"]]))
        break

    avg_rows = [r for r in done if r["average"] is not None]
    if len(avg_rows) >= MIN_YEARS_TREND:
        xs, ys = [r["year"] for r in avg_rows], [r["average"] for r in avg_rows]
        slope, _ = theil_sen(xs, ys)
        _, _, p = mann_kendall(ys)
        if abs(slope) >= MIN_SLOPE:
            confirmed = p < MK_ALPHA
            word = "subindo" if slope > 0 else "caindo"
            found.append(Finding(
                "tendencia", f"Média geral {word} ao longo dos anos", "positivo" if slope > 0 else "observar",
                f"{dec(abs(slope), 2)} ponto por ano em {len(avg_rows)} anos ({xs[0]}–{xs[-1]}); "
                + ("tendência confirmada (Mann–Kendall p = " + dec(p, 3) + ")." if confirmed else
                   "tendência descritiva: com poucos anos o teste não confirma (p = " + dec(p, 3) + ")."),
                "Inclinação de Theil–Sen de 0,3 ponto por ano ou mais, com 3 anos ou mais.",
                "Manter o que tem funcionado." if slope > 0 else "Rever com a coordenação o que mudou nesses anos.",
                REF["tendencia"], xs))

    if last and last["school_changes"] >= MOBILITY:
        found.append(Finding(
            "mobilidade", "Mudanças frequentes de escola", "observar",
            f"{last['school_changes']} trocas de escola fora da passagem de etapa.",
            "2 ou mais mudanças de escola não estruturais.",
            "Acolhimento e checagem de lacunas de conteúdo entre currículos diferentes.", REF["mobilidade"]))

    if current and current["stage"] in (6, 10):
        found.append(Finding(
            "transicao", f"Primeiro ano de nova etapa ({current['stage_label']})", "observar",
            f"Em {current['year']} o estudante está no {current['stage_label']}.",
            "6º ano e 1ª série do médio: mais professores, nova organização, queda comum de desempenho.",
            "Acolhimento nas primeiras semanas e acompanhamento das primeiras notas.", REF["transicao"],
            [current["year"]]))

    history = [r["average"] for r in done if r["average"] is not None]
    if current and current["average"] is not None and len(history) >= 2:
        diff = current["average"] - mean(history)
        if diff <= -DROP:
            found.append(Finding(
                "proprio", "Ano atual abaixo do próprio histórico", "observar",
                f"Média parcial {dec(current['average'], 1)} em {current['year']}; média dos anos anteriores "
                f"{dec(mean(history), 1)}.",
                "Média parcial 1 ponto ou mais abaixo da média dos anos anteriores do próprio estudante.",
                "Conversar cedo: o estudante já mostrou que consegue mais.", REF["proprio"], [current["year"]]))
        elif diff >= DROP:
            found.append(Finding(
                "proprio_acima", "Ano atual acima do próprio histórico", "positivo",
                f"Média parcial {dec(current['average'], 1)}; média dos anos anteriores {dec(mean(history), 1)}.",
                "Média parcial 1 ponto ou mais acima da média dos anos anteriores.", "Reconhecer o avanço.",
                REF["proprio"], [current["year"]]))

    strong = [s for s in (rows[-1]["subjects"] if rows else []) if s["value"] is not None and s["value"] >= 8]
    if strong:
        found.append(Finding(
            "forte", "Componentes fortes", "positivo",
            ", ".join(f"{s['name']} ({dec(s['value'], 1)})" for s in strong[:5]) + f" em {rows[-1]['year']}.",
            "Média 8 ou mais no ano mais recente.", "Usar como ponto de apoio e de autoestima.", ""))

    gaps = [(a["year"], b["year"]) for a, b in zip(rows, rows[1:]) if b["year"] - a["year"] > 1]
    if gaps:
        found.append(Finding(
            "lacuna", "Lacuna no histórico", "dados",
            "Sem registro entre " + "; ".join(f"{a} e {b}" for a, b in gaps) + ".",
            "Anos faltando entre o primeiro e o último registro.",
            "Lançar os anos que faltam a partir do histórico escolar: os sinais acima dependem deles.", REF["dados"]))
    inferred = [r for r in done if r["basis"] in ("deduzido", "estimado")]
    if inferred:
        found.append(Finding(
            "resultado_deduzido", "Resultado final não lançado", "dados",
            "Resultado deduzido ou estimado em " + _years(inferred) + ".",
            "Sem resultado oficial lançado para esses anos.",
            "Lançar o resultado final (Trajetória escolar → Resultados do ano).", REF["dados"],
            [r["year"] for r in inferred]))

    order = {"atencao": 0, "observar": 1, "positivo": 2, "dados": 3}
    return sorted(found, key=lambda f: order[f.level])
