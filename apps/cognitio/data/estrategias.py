"""Banco inicial de estratégias de intervenção (Prompt 16, seção 10.3).

Nível de respaldo, declarado sem exagero:
- "pesquisa": há pesquisa empírica publicada sobre a estratégia (referência ao lado);
  isso NÃO garante efeito em qualquer turma;
- "pratica": prática pedagógica recomendada em documentos curriculares ou na
  literatura didática, sem estudo de efeito citado aqui;
- "experimental": sugestão do projeto, a avaliar com os professores.

Campos: (componente, dimensão, tipos de erro, título, objetivo, procedimentos,
materiais, minutos, acompanhamento, evidência esperada, nível, referências)
"""

ESTRATEGIAS = [
    # Língua Portuguesa
    ("Língua Portuguesa", "Inferência", "compreensao", "Leitura mediada com perguntas de inferência",
     "Levar o estudante a deduzir o que o texto não diz, a partir de pistas.",
     "1) Ler um trecho curto em voz alta. 2) Perguntar o que está escrito (literal). 3) Perguntar o que se pode concluir e "
     "\"que pista do texto mostra isso?\". 4) Comparar informações explícitas e implícitas num quadro de duas colunas. "
     "5) Aumentar gradualmente a extensão e a complexidade dos textos.",
     "Textos curtos do gênero trabalhado; quadro explícito × implícito.", 30,
     "Registrar se o estudante aponta a pista textual que sustenta a inferência.",
     "Resposta a uma pergunta de inferência com justificativa baseada no texto.", "pesquisa",
     "Palincsar, A. S.; Brown, A. L. (1984). Reciprocal teaching of comprehension-fostering and comprehension-monitoring "
     "activities. Cognition and Instruction, 1(2), 117–175. | Kintsch, W. (1998). Comprehension: A paradigm for cognition. "
     "Cambridge University Press."),
    ("Língua Portuguesa", "Localização de informações explícitas", "compreensao", "Ensino recíproco em pequenos grupos",
     "Desenvolver estratégias de compreensão: prever, perguntar, esclarecer e resumir.",
     "1) Modelar as quatro estratégias com um texto. 2) Em grupos de 4, cada estudante assume uma estratégia. "
     "3) Revezar papéis a cada parágrafo. 4) Encerrar com um resumo coletivo.",
     "Cartões com as quatro estratégias; texto informativo.", 40,
     "Observar se os estudantes formulam perguntas sobre o texto e resumem com as próprias palavras.",
     "Resumo de 3 a 5 linhas com as ideias principais.", "pesquisa",
     "Palincsar, A. S.; Brown, A. L. (1984). Cognition and Instruction, 1(2), 117–175."),
    ("Língua Portuguesa", "Decodificação e fluência", "compreensao", "Leitura repetida com apoio do professor",
     "Ganhar precisão e ritmo de leitura em textos adequados à etapa.",
     "1) Escolher texto curto no nível do estudante. 2) Leitura modelo pelo professor. 3) O estudante lê 3 a 4 vezes "
     "com devolutiva sobre precisão e entonação. 4) Registrar a evolução.",
     "Textos curtos; registro de leitura.", 15,
     "Comparar precisão e fluidez entre a primeira e a última leitura da semana.",
     "Leitura em voz alta com menos hesitações no mesmo nível de texto.", "pesquisa",
     "National Reading Panel (2000). Teaching Children to Read: An Evidence-Based Assessment of the Scientific Research "
     "Literature on Reading. Washington, DC: NICHD."),
    ("Língua Portuguesa", "Coerência e organização de ideias", "organizacao|genero", "Planejamento e revisão guiada da escrita",
     "Organizar ideias antes de escrever e revisar com critérios.",
     "1) Analisar um texto-modelo do gênero. 2) Planejar em esquema (ideias, ordem, conectivos). 3) Escrever a primeira "
     "versão. 4) Revisar com lista de critérios curta (gênero, coerência, coesão). 5) Reescrever.",
     "Texto-modelo; esquema de planejamento; lista de revisão.", 50,
     "Comparar primeira e segunda versão nos critérios combinados (não só ortografia).",
     "Segunda versão com progressão de ideias e paragrafação.", "pesquisa",
     "Graham, S.; Perin, D. (2007). A meta-analysis of writing instruction for adolescent students. Journal of Educational "
     "Psychology, 99(3), 445–476."),
    ("Língua Portuguesa", "Convenções da escrita (ortografia, pontuação, concordância)", "convencoes",
     "Revisão focada em uma convenção por vez",
     "Avançar nas convenções da escrita sem confundir com compreensão.",
     "1) Escolher uma regularidade (ex.: pontuação de diálogo). 2) Investigar exemplos. 3) Revisar o próprio texto só "
     "nesse aspecto. 4) Registrar a regra descoberta.",
     "Textos dos próprios estudantes; quadro de regularidades.", 25,
     "Verificar a convenção trabalhada em produção posterior.",
     "Uso correto da convenção em texto novo.", "pratica",
     "BNCC (2018), Língua Portuguesa: eixo Análise linguística/semiótica."),
    # Matemática
    ("Matemática", "Resolução de problemas", "enunciado|estrategia", "Etapas de resolução de problemas com representação",
     "Compreender o enunciado, planejar e verificar a resolução.",
     "1) Reler o problema e dizer com as próprias palavras o que se pede. 2) Identificar dados úteis e inúteis. "
     "3) Representar com desenho, esquema ou barra. 4) Escolher a estratégia e resolver. 5) Verificar se a resposta "
     "faz sentido. 6) Resolver um problema parecido sozinho.",
     "Problemas graduados; papel para esquemas.", 40,
     "Observar em que etapa o estudante trava (compreensão, representação, cálculo ou verificação).",
     "Resolução de problema novo com representação e verificação registradas.", "pratica",
     "Polya, G. (1945). How to Solve It. Princeton University Press."),
    ("Matemática", "Operações e cálculo mental", "calculo|conceitual", "Exemplos resolvidos com problemas de completar",
     "Aprender o procedimento estudando soluções comentadas antes de resolver sozinho.",
     "1) Apresentar 2 exemplos resolvidos e comentados. 2) Dar exercícios com a resolução incompleta para terminar. "
     "3) Retirar o apoio aos poucos. 4) Pedir que o estudante explique um passo.",
     "Fichas com exemplos resolvidos e exercícios graduados.", 30,
     "Verificar se o estudante explica por que cada passo é feito.",
     "Exercícios corretos sem apoio e explicação de um passo.", "pesquisa",
     "Sweller, J.; Cooper, G. A. (1985). The use of worked examples as a substitute for problem solving in learning "
     "algebra. Cognition and Instruction, 2(1), 59–89."),
    ("Matemática", "Sistema de numeração e valor posicional", "conceitual|representacao",
     "Sequência concreto → representação → abstrato",
     "Construir o significado do valor posicional antes do registro simbólico.",
     "1) Manipular material (material dourado, ábaco, cédulas). 2) Representar com desenhos e quadro de ordens. "
     "3) Passar ao registro numérico. 4) Voltar ao concreto quando surgir erro.",
     "Material dourado ou equivalente; quadro de valor posicional.", 40,
     "Pedir que o estudante explique o valor de um algarismo pela posição.",
     "Composição e decomposição corretas com justificativa.", "pesquisa",
     "Witzel, B. S.; Mercer, C. D.; Miller, M. D. (2003). Teaching algebra to students with learning difficulties: An "
     "investigation of an explicit instruction model. Learning Disabilities Research & Practice, 18(2), 121–131."),
    ("Matemática", "Frações e decimais", "conceitual|representacao", "Múltiplas representações de números racionais",
     "Relacionar fração, decimal, porcentagem e reta numérica.",
     "1) Representar a mesma quantidade em barras, círculos e reta numérica. 2) Converter entre fração e decimal. "
     "3) Comparar e ordenar justificando.",
     "Tiras de fração; reta numérica.", 40,
     "Verificar se o estudante localiza frações na reta numérica e justifica comparações.",
     "Comparação correta com justificativa por representação.", "pratica",
     "BNCC (2018), Matemática: unidade temática Números."),
    ("Matemática", "Tabelas, gráficos e estatística", "dados|enunciado", "Leitura guiada de tabelas e gráficos",
     "Ler, interpretar e questionar dados.",
     "1) Identificar título, eixos, legenda e fonte. 2) Responder perguntas de leitura direta. 3) Comparar valores. "
     "4) Tirar uma conclusão e dizer se os dados a sustentam.",
     "Gráficos de jornais ou da própria turma.", 30,
     "Verificar se o estudante distingue leitura direta de interpretação.",
     "Conclusão sustentada pelos dados do gráfico.", "pratica",
     "BNCC (2018), Matemática: unidade temática Probabilidade e estatística."),
    ("Matemática", None, "", "Prática de recuperação espaçada",
     "Consolidar procedimentos e conceitos com retomadas curtas ao longo das semanas.",
     "1) Abrir aulas com 3 a 5 questões rápidas de conteúdos anteriores. 2) Corrigir na hora com devolutiva. "
     "3) Espaçar as retomadas (dias, depois semanas).",
     "Questões curtas de revisão.", 10,
     "Acompanhar acertos nas retomadas ao longo do mês.",
     "Acerto crescente nas questões de retomada.", "pesquisa",
     "Roediger, H. L.; Karpicke, J. D. (2006). Test-enhanced learning. Psychological Science, 17(3), 249–255. | "
     "Cepeda, N. J. et al. (2006). Distributed practice in verbal recall tasks. Psychological Bulletin, 132(3), 354–380."),
    # Ciências
    ("Ciências", "Hipóteses, experimentação e variáveis", "procedimento", "Investigação guiada com controle de variáveis",
     "Planejar um teste justo mudando uma variável por vez.",
     "1) Partir de uma pergunta investigável. 2) Registrar hipótese. 3) Definir o que muda, o que se mede e o que fica "
     "igual. 4) Testar e registrar. 5) Comparar resultado com a hipótese.",
     "Materiais simples do experimento; ficha de investigação.", 50,
     "Verificar se o estudante identifica a variável que mudou e a que foi medida.",
     "Ficha de investigação com variáveis identificadas e conclusão.", "pratica",
     "BNCC (2018), Ciências da Natureza: processo investigativo (competências específicas)."),
    ("Ciências", "Argumentação e comunicação científica", "argumentacao|dados", "Afirmação, evidência e justificativa",
     "Argumentar com base em evidências.",
     "1) Apresentar um fenômeno ou dado. 2) Estudantes escrevem uma afirmação. 3) Apontam a evidência. 4) Justificam com "
     "um conceito. 5) Discutem em grupo afirmações diferentes.",
     "Quadro afirmação–evidência–justificativa.", 40,
     "Verificar se a justificativa liga a evidência ao conceito.",
     "Texto curto com afirmação, evidência e justificativa.", "pesquisa",
     "Osborne, J. (2010). Arguing to learn in science: the role of collaborative, critical discourse. Science, 328(5977), "
     "463–466."),
    ("Ciências", "Explicação de fenômenos e causalidade", "conceito", "Explicação por modelos e desenhos explicativos",
     "Explicar fenômenos usando modelos e representações.",
     "1) Estudante desenha como acha que o fenômeno acontece. 2) Confronta com observação ou experimento. "
     "3) Revisa o desenho e explica a mudança.",
     "Papel, lápis; fenômeno observável.", 40,
     "Comparar o desenho inicial e o revisado.",
     "Desenho explicativo revisado com legenda.", "pratica",
     "BNCC (2018), Ciências da Natureza."),
    # História
    ("História", "Interpretação de fontes", "fonte", "Leitura de fontes: quem, quando, para quê",
     "Ler fontes históricas perguntando autoria, contexto e intenção.",
     "1) Apresentar a fonte. 2) Perguntar quem produziu, quando e para quem. 3) Identificar o ponto de vista. "
     "4) Comparar com outra fonte sobre o mesmo fato.",
     "Duas fontes sobre o mesmo acontecimento.", 40,
     "Verificar se o estudante considera autoria e contexto ao interpretar.",
     "Comparação escrita de duas fontes.", "pesquisa",
     "Wineburg, S. (2001). Historical Thinking and Other Unnatural Acts. Philadelphia: Temple University Press."),
    ("História", "Compreensão temporal e cronologia", "temporalidade", "Linha do tempo comentada",
     "Situar acontecimentos e perceber simultaneidade, sucessão e duração.",
     "1) Construir linha do tempo com escala. 2) Inserir acontecimentos e marcar durações. 3) Perguntar o que acontecia "
     "ao mesmo tempo em outro lugar.",
     "Papel, régua, cartões de acontecimentos.", 40,
     "Verificar ordenação e uso de escala.",
     "Linha do tempo com escala e comentário.", "pratica",
     "BNCC (2018), História: competências específicas."),
    ("História", "Permanências e transformações", "contexto", "Comparação antes e depois",
     "Identificar o que mudou e o que permaneceu.",
     "1) Comparar duas imagens ou relatos de épocas diferentes. 2) Listar mudanças e permanências. 3) Explicar uma causa.",
     "Imagens ou relatos de épocas distintas.", 30,
     "Verificar se o estudante explica ao menos uma causa.",
     "Quadro de mudanças e permanências com explicação.", "pratica",
     "BNCC (2018), História."),
    # Geografia
    ("Geografia", "Leitura cartográfica e escalas", "cartografia|espacial", "Do espaço vivido ao mapa",
     "Ler e produzir representações partindo do lugar conhecido.",
     "1) Desenhar o trajeto casa–escola (croqui). 2) Comparar com mapa ou imagem de satélite. 3) Trabalhar legenda, "
     "orientação e escala. 4) Localizar outros lugares no mapa.",
     "Papel, mapas, imagens de satélite impressas.", 50,
     "Verificar uso de legenda, orientação e noção de escala.",
     "Croqui com legenda e orientação.", "pratica",
     "BNCC (2018), Geografia: unidade temática Formas de representação e pensamento espacial."),
    ("Geografia", "Sociedade e natureza", "conceito|dados", "Estudo do meio com registro de campo",
     "Relacionar ações humanas e dinâmicas naturais observadas no entorno.",
     "1) Preparar roteiro de observação. 2) Registrar paisagem, usos e problemas. 3) Organizar dados em tabela. "
     "4) Propor explicação e ação.",
     "Roteiro de campo; prancheta.", 90,
     "Verificar se a explicação relaciona elementos naturais e sociais.",
     "Relatório de campo com dados e explicação.", "pratica",
     "BNCC (2018), Geografia."),
    # Arte
    ("Arte", "Leitura e apreciação de produções", "", "Leitura de imagem em etapas",
     "Ampliar a leitura de produções artísticas sem julgar talento.",
     "1) Descrever o que se vê. 2) Analisar elementos (cor, forma, composição). 3) Interpretar sentidos. "
     "4) Relacionar ao contexto cultural.",
     "Reproduções de obras; roteiro de leitura.", 40,
     "Registrar a ampliação do vocabulário e das relações feitas.",
     "Comentário oral ou escrito sobre a obra.", "pratica",
     "BNCC (2018), Arte: competências específicas."),
    ("Arte", "Expressão e criação", "", "Processo criativo com registro de etapas",
     "Valorizar o processo: experimentar, escolher, revisar.",
     "1) Propor desafio aberto. 2) Experimentar materiais. 3) Registrar escolhas (diário de processo). "
     "4) Compartilhar e comentar processos.",
     "Materiais variados; diário de processo.", 50,
     "Acompanhar o diário de processo, não o 'resultado bonito'.",
     "Diário com experimentações e escolhas.", "pratica",
     "BNCC (2018), Arte."),
    # Educação Física
    ("Educação Física", "Estratégias e cooperação", "", "Jogos cooperativos com problematização",
     "Desenvolver estratégia e cooperação, sem classificar pelo desempenho físico.",
     "1) Jogo com objetivo coletivo. 2) Parar e perguntar o que funcionou. 3) Ajustar regras ou estratégias. "
     "4) Jogar de novo e comparar.",
     "Espaço livre; materiais do jogo.", 45,
     "Observar participação, propostas de estratégia e respeito às regras.",
     "Relato do grupo sobre a estratégia escolhida.", "pratica",
     "BNCC (2018), Educação Física: competências específicas."),
    ("Educação Física", "Respeito, cultura corporal e saúde", "", "Roda de conversa sobre práticas corporais",
     "Refletir sobre corpo, saúde, respeito e preconceitos nas práticas.",
     "1) Vivenciar a prática. 2) Conversar sobre sensações, regras e exclusões. 3) Propor mudanças inclusivas.",
     "Espaço de roda.", 20,
     "Registrar contribuições na conversa.",
     "Proposta coletiva de prática mais inclusiva.", "pratica",
     "BNCC (2018), Educação Física."),
    # Ensino Religioso
    ("Ensino Religioso", "Respeito, diálogo e alteridade", "", "Pesquisa e diálogo sobre manifestações culturais",
     "Conhecer manifestações diversas com respeito, sem avaliar crença.",
     "1) Pesquisar uma manifestação cultural ou religiosa. 2) Apresentar ao grupo. 3) Dialogar sobre semelhanças e "
     "diferenças com respeito.",
     "Fontes de pesquisa; roteiro.", 45,
     "Observar escuta e respeito no diálogo (nunca a fé do estudante).",
     "Apresentação e participação respeitosa no diálogo.", "pratica",
     "BNCC (2018), Ensino Religioso: competências específicas."),
    # Língua Inglesa
    ("Língua Inglesa", "Compreensão escrita", "compreensao|vocabulario", "Leitura com estratégias de antecipação",
     "Compreender textos usando título, imagens e palavras cognatas.",
     "1) Antecipar o assunto pelo título e imagens. 2) Localizar cognatas. 3) Leitura rápida (skimming) e de busca "
     "(scanning). 4) Responder perguntas.",
     "Textos curtos autênticos.", 30,
     "Verificar uso de estratégias e compreensão geral.",
     "Respostas de compreensão geral e específica.", "pratica",
     "BNCC (2018), Língua Inglesa: eixo Leitura."),
    ("Língua Inglesa", "Produção oral e interação", "interacao", "Diálogos com apoio de modelos",
     "Interagir oralmente em situações do cotidiano.",
     "1) Ouvir um diálogo modelo. 2) Praticar em pares com cartões de apoio. 3) Variar a situação.",
     "Cartões de diálogo.", 25,
     "Observar a interação com apoio cada vez menor.",
     "Diálogo curto em situação nova.", "pratica",
     "BNCC (2018), Língua Inglesa: eixo Oralidade."),
    # Competências digitais / pensamento computacional
    ("Competências digitais", "Algoritmos e sequenciamento lógico", "", "Atividades desplugadas de algoritmos",
     "Descrever passos ordenados que resolvem um problema, com ou sem computador.",
     "1) Descrever um procedimento do cotidiano em passos. 2) Testar a sequência com um colega que executa ao pé da "
     "letra. 3) Corrigir passos ambíguos. 4) Representar em fluxograma.",
     "Papel; cartões de comandos.", 40,
     "Verificar se a sequência é completa e sem ambiguidade.",
     "Fluxograma ou lista de passos testada.", "pesquisa",
     "Wing, J. M. (2006). Computational thinking. Communications of the ACM, 49(3), 33–35. | Brennan, K.; Resnick, M. "
     "(2012). New frameworks for studying and assessing the development of computational thinking. AERA Annual Meeting."),
    ("Competências digitais", "Uso crítico de informações", "", "Checagem de informações em três perguntas",
     "Avaliar a confiabilidade de informações encontradas na internet.",
     "1) Quem publicou? 2) Que evidência apresenta? 3) Outras fontes confirmam? Aplicar a notícias reais e discutir.",
     "Notícias impressas ou capturas de tela.", 30,
     "Verificar se o estudante justifica a confiabilidade com as três perguntas.",
     "Avaliação escrita de uma notícia com justificativa.", "experimental",
     "Lei nº 14.533/2023 (PNED), art. 3º, III (cultura digital)."),
    # Geral (formativa)
    (None, None, "", "Verificação curta com devolutiva imediata",
     "Confirmar uma hipótese sobre a aprendizagem antes de intervir.",
     "1) Elaborar 2 a 3 questões curtas sobre a habilidade. 2) Aplicar em outra situação (oral, prática ou escrita). "
     "3) Dar devolutiva específica e registrar o resultado como evidência.",
     "Questões curtas.", 10,
     "Comparar o resultado com as evidências anteriores.",
     "Nova evidência registrada para confirmar ou descartar a hipótese.", "pesquisa",
     "Black, P.; Wiliam, D. (1998). Assessment and classroom learning. Assessment in Education, 5(1), 7–74. | Hattie, J.; "
     "Timperley, H. (2007). The power of feedback. Review of Educational Research, 77(1), 81–112."),
]
