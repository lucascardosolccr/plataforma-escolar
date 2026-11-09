"""Definição de cada indicador dos painéis de BI.

Nenhum número aparece num painel sem a definição correspondente aqui: o que
mede, para que serve, a fórmula, a fonte, a regra para dado ausente, como
interpretar e as limitações. O mesmo texto alimenta o "ⓘ" de cada indicador
e a página de metodologia (``analytics:methodology``) — uma fonte só, para a
explicação nunca divergir do cálculo (ver ``bi.py``).

Distinção usada em toda a plataforma (Prompt 13, §8):
- **observado**: registro lançado por alguém (nota, presença, entrega);
- **calculado**: indicador derivado por fórmula fixa a partir dos observados;
- **sugestão**: regra transparente que aponta algo para avaliação humana.
Não há projeções nem modelos preditivos (ver ``docs/BI_METODOLOGIA.md``).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    group: str
    measures: str
    formula: str
    source: str
    missing: str
    interpretation: str
    limitations: str
    kind: str = "calculado"  # observado | calculado | sugestão


_M = [
    # ---------------- Desempenho ----------------
    Metric(
        "subject_average", "Média por disciplina", "Desempenho",
        "O resultado do estudante em cada disciplina no período.",
        "Regra da disciplina (aritmética, ponderada pelo peso, melhor nota ou soma) "
        "aplicada às notas das avaliações publicadas com data no período.",
        "Notas (Grade) de avaliações publicadas; regra em Regras e limites.",
        "Disciplina sem nota no período não tem média (—). Nota em branco não conta como zero.",
        "Comparar com a média de aprovação da disciplina (padrão 6,0).",
        "Rascunhos não entram. Avaliações sem data de período não existem (a data é obrigatória).",
    ),
    Metric(
        "overall_average", "Média geral", "Desempenho",
        "Um resumo do desempenho no período, dando o mesmo peso a cada disciplina.",
        "Média aritmética das médias por disciplina do período.",
        "Médias por disciplina.",
        "Sem nenhuma média por disciplina, não há média geral (—).",
        "Resumo apenas: o detalhe por disciplina é o que orienta a ação.",
        "Esconde diferenças entre disciplinas; disciplinas com uma única nota pesam o mesmo "
        "que as demais. A LDB (art. 24, V) pede prevalência do qualitativo sobre o quantitativo.",
    ),
    Metric(
        "average_delta", "Variação em relação ao período anterior", "Desempenho",
        "Se a média subiu ou caiu em relação ao período imediatamente anterior, de mesmo tamanho.",
        "Média do período − média do período anterior (em pontos).",
        "Notas dos dois períodos.",
        "Sem média em algum dos dois períodos, não há variação (—).",
        "Variação de ±1,0 ponto ou mais é destacada.",
        "Avaliações diferentes nos dois períodos; não indica causa.",
    ),
    Metric(
        "trend", "Tendência das notas", "Desempenho",
        "A direção geral das notas ao longo do período.",
        "Inclinação da reta de mínimos quadrados das notas pela data, em pontos por mês. "
        "Alta: ≥ +0,3/mês; queda: ≤ −0,3/mês; estável entre os dois.",
        "Notas do período com a data da avaliação.",
        "Exige ao menos 4 notas em ao menos 2 meses; abaixo disso, \"dados insuficientes\".",
        "Descreve o passado do período; não é previsão.",
        "Sensível a avaliações de dificuldade diferente e a notas isoladas extremas.",
    ),
    Metric(
        "class_comparison", "Comparação com a turma", "Desempenho",
        "Posição do estudante em relação ao conjunto da turma, por disciplina.",
        "Média da turma = média aritmética das médias individuais dos estudantes ativos.",
        "Notas da turma no período.",
        "Turma com menos de 5 estudantes com nota: comparação não exibida (proteção contra identificação).",
        "Referência de contexto, não ranking.",
        "Exibida somente à equipe e ao professor. Não aparece para família e estudante.",
    ),
    Metric(
        "grade_distribution", "Distribuição das notas", "Desempenho",
        "Como as notas se espalham por faixas.",
        "Contagem de notas em faixas de 2 pontos (0–2, 2–4, …, 8–10; acima de 10 em faixa própria).",
        "Notas do período.",
        "Sem notas, distribuição vazia.",
        "Concentração nas faixas baixas sugere retomada; espalhamento grande, turma heterogênea.",
        "Escala pensada para 0–10; regra \"soma\" pode gerar valores acima de 10.",
    ),
    Metric(
        "evaluation_stats", "Resultado por avaliação", "Desempenho",
        "Média, mediana, mínimo, máximo, desvio padrão e lançamentos de cada avaliação.",
        "Estatística descritiva sobre as notas lançadas da avaliação; "
        "pendentes = estudantes ativos da turma sem nota.",
        "Notas da avaliação; matrículas ativas.",
        "Sem notas lançadas, estatísticas —. Pendência é diferente de nota zero.",
        "Média baixa com desvio pequeno indica dificuldade coletiva; desvio grande, heterogeneidade.",
        "Desvio padrão populacional; com menos de 3 notas não é exibido.",
    ),
    Metric(
        "recovery", "Resultado de recuperação", "Desempenho",
        "Se a avaliação de recuperação alcançou a média de aprovação.",
        "Nota da avaliação marcada como Recuperação comparada à média da disciplina antes dela.",
        "Avaliações com tipo \"Recuperação\".",
        "Só existe para avaliações que o professor marcou com esse tipo (campo novo, opcional).",
        "Indica o resultado da recuperação, não a regra de substituição de nota da escola.",
        "Avaliações anteriores ao campo ficam como \"não informado\".",
    ),
    # ---------------- Frequência ----------------
    Metric(
        "attendance_percent", "Frequência", "Frequência",
        "Proporção de dias com chamada em que o estudante esteve presente.",
        "(presenças + atrasos) ÷ dias com chamada registrada para o estudante × 100.",
        "Registros de frequência (chamada diária da turma).",
        "Sem nenhum registro no período: — (não é 0%).",
        "Comparar com o mínimo legal de 75% (LDB, art. 24, VI) e com o limite da escola.",
        "A chamada é diária por turma, não por aula ou disciplina; \"aulas previstas\" não são "
        "registradas, então o divisor são os dias com chamada.",
        "observado",
    ),
    Metric(
        "absences", "Faltas", "Frequência",
        "Quantidade de dias com falta registrada.",
        "Contagem de registros com situação \"falta\" no período.",
        "Registros de frequência.",
        "Dia sem chamada não é falta.",
        "Ver junto do percentual e das justificativas.",
        "Atraso conta como presença.",
        "observado",
    ),
    Metric(
        "justified_absences", "Faltas justificadas", "Frequência",
        "Faltas cobertas por justificativa aprovada pela secretaria.",
        "Faltas cuja data está dentro do período de uma justificativa aprovada.",
        "Justificativas de falta (situação aprovada) × registros de falta.",
        "Justificativa em análise ou recusada não conta.",
        "Justificar não altera a frequência oficial: a falta continua contada.",
        "Depende de a família enviar e de a secretaria analisar.",
    ),
    Metric(
        "absence_limit", "Proximidade do limite de faltas", "Frequência",
        "Se as faltas se aproximam do limite configurado pela escola.",
        "Faltas ÷ dias com chamada × 100, comparado ao limite (Regras e limites). "
        "Atenção a partir de 80% do limite; acima do limite, alerta.",
        "Registros de frequência; limite de faltas da escola.",
        "Sem registros, não avaliado.",
        "Sinal preventivo para conversa com a família, não reprovação.",
        "A frequência oficial para aprovação é consolidada pela secretaria ao fim do período. O painel "
        "mostra junto a situação do ano letivo (faltas permitidas = dias letivos do calendário × limite), "
        "a mesma da Agenda e faltas e dos avisos às famílias.",
    ),
    Metric(
        "absence_streak", "Sequência de faltas", "Frequência",
        "Maior série de faltas em dias de chamada consecutivos.",
        "Maior número de registros consecutivos (ordenados por data) com situação \"falta\".",
        "Registros de frequência.",
        "Exibida a partir de 3 faltas seguidas.",
        "Sequências pedem contato com a família.",
        "Dias sem chamada interrompem a contagem pelo calendário de chamadas, não pelo civil.",
    ),
    Metric(
        "attendance_weekday", "Faltas por dia da semana", "Frequência",
        "Se as faltas se concentram em algum dia.",
        "Faltas ÷ dias com chamada, separado por dia da semana.",
        "Registros de frequência.",
        "Exibido com ao menos 10 registros no período.",
        "Concentração num dia pode indicar uma questão de rotina a conversar.",
        "Poucos registros por dia da semana tornam o percentual instável.",
    ),
    # ---------------- Atividades ----------------
    Metric(
        "activities_proposed", "Atividades propostas", "Atividades",
        "Atividades de casa publicadas para a turma enquanto o estudante estava nela.",
        "Atividades publicadas (não canceladas) com data de publicação até hoje, entrega no período, "
        "que alcançam o estudante pelas matrículas.",
        "Atividades de casa; matrículas (com datas de entrada e saída).",
        "Atividade sem prazo entra pelo mês de publicação.",
        "Base para os percentuais de entrega.",
        "Canceladas não entram.",
        "observado",
    ),
    Metric(
        "delivery_rate", "Taxa de entrega", "Atividades",
        "Entre as atividades com entrega registrada pelo professor, quantas foram entregues.",
        "(entregues no prazo + entregues com atraso) ÷ (entregues + não entregues) × 100.",
        "Registros de entrega (Submission) lançados pelo professor.",
        "Atividade sem registro NÃO conta como não entregue: entra em \"sem registro\".",
        "Abaixo de 60% merece conversa; ver também a cobertura de registro.",
        "Depende de o professor registrar as entregas.",
    ),
    Metric(
        "record_coverage", "Cobertura de registro", "Atividades",
        "Quanto das atividades com prazo vencido teve a entrega registrada.",
        "Atividades com registro ÷ atividades com prazo vencido × 100.",
        "Atividades e registros de entrega.",
        "—",
        "Cobertura baixa torna a taxa de entrega pouco representativa.",
        "Indicador de qualidade do dado, não do estudante.",
    ),
    Metric(
        "on_time_rate", "Entregas no prazo", "Atividades",
        "Entre as entregas feitas, quantas foram no prazo.",
        "entregues no prazo ÷ (no prazo + com atraso) × 100.",
        "Registros de entrega com a situação \"Entregue com atraso\" (nova).",
        "Sem entregas, —.",
        "Atrasos frequentes sugerem conversar sobre organização da rotina.",
        "A situação \"com atraso\" passou a existir agora; registros antigos aparecem como \"no prazo\".",
    ),
    Metric(
        "group_participation", "Participação em trabalhos em grupo", "Atividades",
        "Em quantos trabalhos em grupo o estudante participou e como foram as entregas.",
        "Trabalhos publicados no período em que o estudante integra um grupo; "
        "entregas pela situação registrada (por grupo ou por integrante).",
        "Trabalhos em grupo, grupos, integrantes e entregas.",
        "Sem grupo formado, o trabalho não conta como participação.",
        "Complementa a visão das atividades individuais.",
        "Não mede a contribuição individual dentro do grupo.",
        "observado",
    ),
    # ---------------- Turma e instituição ----------------
    Metric(
        "follow_up", "Estudantes para acompanhamento", "Turma",
        "Quantos estudantes atendem a algum critério de atenção configurado no painel.",
        "Estudante com: média abaixo da aprovação em pelo menos N disciplinas, OU frequência abaixo "
        "do mínimo (100 − limite de faltas), OU taxa de entrega abaixo de X% (com ao menos 3 registros). "
        "N e X são ajustáveis no próprio painel.",
        "Médias, frequência e entregas do período.",
        "Critério sem dado (ex.: sem chamada) não é contado como atendido nem como violado.",
        "Lista de apoio para o conselho de classe e o planejamento, não classificação do estudante.",
        "Critérios simples e transparentes; não substituem a avaliação do professor.",
    ),
    Metric(
        "evolution_observed", "Estudantes com evolução observada", "Turma",
        "Quantos estudantes melhoraram a média da primeira para a segunda metade do período.",
        "Média geral da 2ª metade − média geral da 1ª metade ≥ +0,5 ponto.",
        "Notas do período dividido ao meio pela data.",
        "Estudante sem nota em alguma das metades não entra na conta.",
        "Indica melhora observada, não a causa.",
        "Avaliações diferentes em cada metade.",
    ),
    Metric(
        "enrollment_movement", "Movimentação escolar", "Instituição",
        "Entradas e saídas de estudantes nas turmas no período.",
        "Matrículas com entrada no período (ingressos) e com saída no período por situação "
        "(transferido, desistente, concluído).",
        "Matrículas (datas de entrada e saída).",
        "Matrícula sem data de saída não conta como saída.",
        "Transferência entre turmas da escola gera uma saída e uma entrada.",
        "Datas de saída lançadas depois do fato podem cair em outro período.",
        "observado",
    ),
    Metric(
        "small_group", "Proteção de grupos pequenos", "Instituição",
        "Evita identificar estudantes em comparações de grupos com poucas pessoas.",
        "Grupos com menos de 5 estudantes têm médias e percentuais ocultos nas comparações coletivas.",
        "—", "—",
        "\"Grupo pequeno\" indica dado ocultado de propósito, não ausente.",
        "Os números continuam visíveis nos painéis individuais, para quem tem acesso a eles.",
    ),
    # ---------------- Sugestões ----------------
    Metric(
        "insights", "Sugestões pedagógicas", "Inteligência pedagógica",
        "Pontos que merecem um olhar do professor, cada um com a regra e o dado que o originou.",
        "Regras fixas e públicas (ver lista na metodologia), sem modelo estatístico nem pontuação.",
        "Indicadores calculados acima.",
        "Regra sem dado suficiente não dispara.",
        "Sugestão para avaliação do professor; nunca decisão nem diagnóstico.",
        "Não estabelecem causa. Não usam atributos pessoais. Não rotulam o estudante.",
        "sugestão",
    ),
    Metric(
        "intervention_effect", "Antes e depois do plano de acompanhamento", "Inteligência pedagógica",
        "Como estavam as notas e a frequência antes e depois do início de um plano.",
        "Média das notas e frequência nos 60 dias anteriores à criação do plano × nos 60 dias seguintes.",
        "Planos de acompanhamento; notas; frequência.",
        "Exige ao menos 2 notas em cada lado para a comparação de notas.",
        "Mostra o que foi observado ao redor do plano.",
        "Associação no tempo, não efeito do plano: outras coisas mudam ao mesmo tempo.",
    ),
    # ---------------- Cadastro, rotina e impressão ----------------
    Metric(
        "photo_coverage", "Estudantes ativos com foto", "Cadastro e rotina",
        "Quanto do cadastro de estudantes já tem foto de identificação.",
        "Estudantes ativos com foto ÷ estudantes ativos × 100. Dispensas justificadas são contadas à parte.",
        "Fichas de estudantes; dispensas de fotografia.",
        "Sem estudantes ativos, \"—\".",
        "Pendência cadastral; não mede nada pedagógico.",
        "A foto é só identificação visual; não há reconhecimento facial.",
        "observado",
    ),
    Metric(
        "school_days_left", "Dias letivos restantes", "Cadastro e rotina",
        "Quantos dias de aula ainda há no ano, pelo calendário oficial.",
        "Dias úteis de hoje ao fim do ano letivo, menos dias sem aula (feriado, recesso, férias, planejamento, "
        "suspensão), mais dias letivos extras.",
        "Ano letivo (início e fim); calendário oficial publicado.",
        "Sem datas do ano ou sem calendário publicado, nada é mostrado (nunca uma conta inventada).",
        "Muda sozinho quando o calendário muda.",
        "Depende de o calendário estar completo e correto.",
    ),
    Metric(
        "prints_on_time", "Impressões entregues no prazo", "Cadastro e rotina",
        "Se a fila de impressão está atendendo os professores a tempo.",
        "Pedidos entregues cuja impressão foi registrada até a data desejada ÷ pedidos entregues × 100.",
        "Pedidos de impressão e o histórico de cada pedido.",
        "Sem pedidos entregues no período, \"—\".",
        "Ajuda a planejar a impressão; não avalia pessoas.",
        "Depende de a secretaria registrar cada passo no dia em que acontece.",
    ),
    Metric(
        "module_usage", "Utilização da plataforma", "Gestão",
        "Quanto cada módulo foi usado no período e quantas contas entraram, por perfil.",
        "Registros criados no período em cada tabela (chamada conta turma e data uma vez; entrega conta "
        "a última atualização do registro); contas distintas com login no período.",
        "Tabelas de atividades, trabalhos, avaliações, frequência, entregas, ocorrências, planos de aula, "
        "comunicados, mensagens, solicitações, conteúdos de prova e dúvidas; logins da auditoria.",
        "Sem registro, o módulo aparece com 0: aqui zero é a contagem real, não falta de dado.",
        "Mostra adoção da plataforma. Não mede a qualidade do trabalho de nenhum profissional.",
        "Registro feito fora da plataforma (papel, outro sistema) não aparece.",
    ),
]

METRICS = {m.key: m for m in _M}
GROUPS = list(dict.fromkeys(m.group for m in _M))


INSIGHT_RULES = [
    ("Média abaixo da aprovação", "Média da disciplina no período < média de aprovação da disciplina."),
    ("Queda na disciplina", "Média da disciplina caiu 1,0 ponto ou mais em relação ao período anterior "
     "(ao menos 2 notas em cada período)."),
    ("Melhora na disciplina", "Média da disciplina subiu 1,0 ponto ou mais em relação ao período anterior."),
    ("Tendência de alta", "Inclinação das notas ≥ +0,3 ponto/mês com ao menos 4 notas em 2 meses."),
    ("Frequência perto do limite", "Faltas ≥ 80% do limite da escola (ou acima dele)."),
    ("Sequência de faltas", "3 ou mais faltas em dias de chamada consecutivos."),
    ("Entrega de atividades baixa", "Taxa de entrega < 60% com ao menos 3 entregas registradas."),
    ("Entregas sem registro", "3 ou mais atividades com prazo vencido sem registro de entrega "
     "(aviso de qualidade do dado ao professor)."),
    ("Dificuldade recorrente registrada", "2 ou mais observações pedagógicas com dificuldade na mesma "
     "disciplina (somente para quem vê observações)."),
]
