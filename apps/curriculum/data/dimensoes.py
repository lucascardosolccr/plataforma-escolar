"""Matriz analítica do EIA-Cognitio por componente (Prompt 16, seção 6).

Natureza: **escolha metodológica do projeto**, não texto normativo. Os grupos e as
dimensões seguem a especificação do projeto e a organização da própria BNCC
(práticas de linguagem, unidades temáticas). As palavras-chave só SUGEREM a
ligação entre uma habilidade oficial e uma dimensão; o professor confirma.

Cada linha: (componente, grupo, dimensão, palavras-chave separadas por "|", o que observar)
"""

DIMENSIONS = [
    # Língua Portuguesa
    ("Língua Portuguesa", "Leitura e compreensão", "Decodificação e fluência", "decodific|fluência|ler em voz alta|silenciosamente",
     "Lê com precisão e ritmo adequados à etapa."),
    ("Língua Portuguesa", "Leitura e compreensão", "Localização de informações explícitas", "localizar informaç|informações explícitas|identificar informaç",
     "Encontra no texto a informação pedida."),
    ("Língua Portuguesa", "Leitura e compreensão", "Inferência", "inferir|implícit|inferência",
     "Deduz o que não está escrito, a partir de pistas do texto."),
    ("Língua Portuguesa", "Leitura e compreensão", "Tema, finalidade e ideia central", "ideia central|tema|finalidade|assunto principal",
     "Reconhece o assunto e o propósito do texto."),
    ("Língua Portuguesa", "Leitura e compreensão", "Relações de causa e consequência", "causa|consequência|relações lógico",
     "Explica por que algo acontece e o que decorre disso no texto."),
    ("Língua Portuguesa", "Leitura e compreensão", "Argumentos e análise crítica", "argument|ponto de vista|posicionamento|fato e opinião|opinião|crítica",
     "Distingue fato de opinião e avalia argumentos."),
    ("Língua Portuguesa", "Leitura e compreensão", "Textos multimodais", "multissemiótic|multimodal|imagens|infográfic|recursos visuais",
     "Integra texto verbal, imagem e outros recursos."),
    ("Língua Portuguesa", "Produção textual", "Adequação ao gênero e à finalidade", "gênero|planejar|produzir textos|interlocutor|situação comunicativa",
     "Escreve no gênero pedido, para o leitor e a finalidade indicados."),
    ("Língua Portuguesa", "Produção textual", "Coerência e organização de ideias", "coerência|organização|progressão temática|paragrafação",
     "Ideias encadeadas, sem contradição, com progressão."),
    ("Língua Portuguesa", "Produção textual", "Coesão", "coesão|conectivos|articuladores|substituições lexicais|pronomes",
     "Liga frases e parágrafos com conectivos e retomadas."),
    ("Língua Portuguesa", "Produção textual", "Convenções da escrita (ortografia, pontuação, concordância)", "ortografia|pontuação|concordância|grafia|acentuação",
     "Convenções da escrita, avaliadas separadamente da compreensão."),
    ("Língua Portuguesa", "Oralidade e análise linguística", "Oralidade", "oral|exposição|apresentação oral|debate|escuta",
     "Organiza a fala, escuta e participa."),
    ("Língua Portuguesa", "Oralidade e análise linguística", "Reflexão sobre a língua", "análise linguística|morfossintax|classes de palavras|variação linguística|semântic",
     "Reflete sobre usos e variedades da língua."),
    # Matemática
    ("Matemática", "Números", "Sistema de numeração e valor posicional", "sistema de numeração|valor posicional|ordens|composição e decomposição",
     "Compreende ordens, classes e o valor do algarismo pela posição."),
    ("Matemática", "Números", "Operações e cálculo mental", "adição|subtração|multiplicação|divisão|cálculo mental|potenciação|operações",
     "Escolhe e executa operações; usa estratégias de cálculo."),
    ("Matemática", "Números", "Frações e decimais", "fração|frações|decimal|racionais|porcentage",
     "Representa, compara e opera números racionais."),
    ("Matemática", "Resolução de problemas", "Resolução de problemas", "resolver e elaborar problemas|problemas",
     "Interpreta o enunciado, planeja, executa e verifica."),
    ("Matemática", "Álgebra", "Padrões, regularidades e álgebra", "regularidade|padrão|sequência|álgebra|equação|expressões|proporcionalidade",
     "Generaliza padrões e relações entre grandezas."),
    ("Matemática", "Geometria", "Geometria e localização espacial", "figuras|geométric|ângulo|polígono|plano cartesiano|localização|deslocamento",
     "Reconhece formas, propriedades e posições."),
    ("Matemática", "Grandezas e medidas", "Grandezas e medidas", "medida|medidas|comprimento|massa|capacidade|área|perímetro|volume|tempo",
     "Mede, estima e converte unidades."),
    ("Matemática", "Probabilidade e estatística", "Tabelas, gráficos e estatística", "tabela|gráfico|pesquisa|dados|estatística|média",
     "Lê, organiza e interpreta dados."),
    ("Matemática", "Probabilidade e estatística", "Probabilidade", "probabilidade|chance|aleatóri|eventos",
     "Avalia possibilidades e chances."),
    # Ciências
    ("Ciências", "Investigação científica", "Observação e perguntas", "observar|observação|questões|perguntas",
     "Observa com intenção e formula perguntas investigáveis."),
    ("Ciências", "Investigação científica", "Hipóteses, experimentação e variáveis", "hipótese|experiment|testar|variáveis|investigar|planejar",
     "Propõe hipóteses e testa controlando condições."),
    ("Ciências", "Investigação científica", "Interpretação de resultados e evidências", "resultados|evidências|interpretar|concluir|registrar",
     "Interpreta dados e tira conclusões coerentes."),
    ("Ciências", "Compreensão de fenômenos", "Explicação de fenômenos e causalidade", "explicar|fenômeno|relacionar|causa|efeito|transformações",
     "Explica fenômenos com conceitos científicos."),
    ("Ciências", "Comunicação", "Argumentação e comunicação científica", "argument|comunicar|divulgar|discutir|propor",
     "Comunica e defende conclusões com base em evidências."),
    # História
    ("História", "Tempo histórico", "Compreensão temporal e cronologia", "tempo|cronolog|passado|presente|futuro|linha do tempo|marcos",
     "Situa acontecimentos no tempo e ordena sequências."),
    ("História", "Tempo histórico", "Permanências e transformações", "permanência|mudança|transformações|continuidade",
     "Identifica o que muda e o que permanece."),
    ("História", "Fontes e sujeitos", "Interpretação de fontes", "fontes|documentos|registros|vestígios|iconográf",
     "Lê e questiona fontes históricas."),
    ("História", "Fontes e sujeitos", "Sujeitos históricos e perspectivas", "sujeitos|grupos sociais|povos|perspectiva|ponto de vista|protagonismo",
     "Reconhece agentes e compara versões."),
    ("História", "Processos", "Causalidade e contextualização", "contexto|processo|causas|consequências|relações",
     "Relaciona causas, contextos e consequências."),
    ("História", "Processos", "Argumentação histórica", "argument|posicionar|debater|discutir",
     "Argumenta com base em evidências históricas."),
    # Geografia
    ("Geografia", "Pensamento espacial", "Orientação e localização", "orientação|localiz|pontos de referência|direções|coordenadas",
     "Orienta-se e localiza lugares."),
    ("Geografia", "Pensamento espacial", "Leitura cartográfica e escalas", "mapa|cartográf|escala|representação|planta|croqui",
     "Lê e produz mapas, entende escalas."),
    ("Geografia", "Conceitos geográficos", "Paisagem, lugar, território e região", "paisagem|lugar|território|região|espaço geográfico",
     "Usa os conceitos estruturantes da Geografia."),
    ("Geografia", "Conceitos geográficos", "Sociedade e natureza", "natureza|ambient|recursos naturais|clima|relevo|água|sustentab",
     "Relaciona ações humanas e dinâmicas naturais."),
    ("Geografia", "Análise", "Dinâmicas socioespaciais e dados geográficos", "população|urbana|rural|trabalho|produção|dados|gráfico|circulação",
     "Interpreta dados e processos socioespaciais."),
    # Arte
    ("Arte", "Criação", "Expressão e criação", "criar|produzir|compor|experimentar|improvis",
     "Cria e experimenta; o processo vale, não o 'talento'."),
    ("Arte", "Criação", "Materiais e elementos da linguagem", "elementos|materiais|técnicas|cores|formas|ritmo|timbre|movimento",
     "Explora materiais e elementos da linguagem artística."),
    ("Arte", "Fruição e reflexão", "Leitura e apreciação de produções", "apreciar|fruir|analisar|interpretar|reconhecer",
     "Lê e comenta produções artísticas."),
    ("Arte", "Fruição e reflexão", "Repertório e contexto cultural", "patrimônio|matrizes|culturas|cultural|contextos|tradições",
     "Relaciona produções a contextos e culturas."),
    # Educação Física
    ("Educação Física", "Práticas corporais", "Conhecimento de práticas e regras", "regras|práticas corporais|jogos|esportes|brincadeiras|lutas|danças|ginástica",
     "Conhece práticas e entende regras."),
    ("Educação Física", "Práticas corporais", "Estratégias e cooperação", "estratégias|cooperação|táticas|coletiv|equipe",
     "Planeja ações e coopera; desempenho físico isolado não classifica."),
    ("Educação Física", "Reflexão", "Respeito, cultura corporal e saúde", "respeito|preconceito|saúde|corpo|cultura corporal|valores",
     "Reflete sobre corpo, saúde e convivência."),
    # Ensino Religioso
    ("Ensino Religioso", "Diversidade", "Manifestações e tradições", "manifestações|tradições|símbolos|ritos|narrativas|textos sagrados",
     "Identifica manifestações culturais e religiosas (sem avaliar fé)."),
    ("Ensino Religioso", "Diversidade", "Respeito, diálogo e alteridade", "respeit|diálogo|alteridade|diversidade|convivência",
     "Dialoga e respeita diferentes tradições e convicções."),
    ("Ensino Religioso", "Reflexão", "Reflexão ética", "ética|valores|princípios|direitos humanos|vida",
     "Reflete eticamente sobre fenômenos culturais."),
    # Língua Inglesa
    ("Língua Inglesa", "Compreensão", "Compreensão oral", "compreensão oral|ouvir|escuta|áudio",
     "Compreende falas e áudios."),
    ("Língua Inglesa", "Compreensão", "Compreensão escrita", "leitura|ler|textos|estratégias de leitura",
     "Compreende textos escritos."),
    ("Língua Inglesa", "Produção", "Produção oral e interação", "produção oral|interagir|interação|falar|diálogo",
     "Fala e interage em situações comunicativas."),
    ("Língua Inglesa", "Produção", "Produção escrita", "produzir|escrita|escrever",
     "Escreve textos adequados à situação."),
    ("Língua Inglesa", "Conhecimentos linguísticos", "Vocabulário e uso contextualizado", "léxico|vocabulário|gramática|uso de|expressões",
     "Usa vocabulário e estruturas em contexto."),
    # Núcleo transversal de competências digitais (PNED e prompt, seção 6.10)
    ("Competências digitais", "Pensamento computacional", "Decomposição de problemas", "decompor|decomposição|etapas",
     "Divide um problema em partes menores."),
    ("Competências digitais", "Pensamento computacional", "Reconhecimento de padrões", "padrão|padrões|regularidade",
     "Percebe regularidades que se repetem."),
    ("Competências digitais", "Pensamento computacional", "Abstração", "abstração|generaliz|modelar|modelo",
     "Foca no essencial e generaliza."),
    ("Competências digitais", "Pensamento computacional", "Algoritmos e sequenciamento lógico", "algoritmo|fluxograma|sequência de passos|instruções",
     "Descreve passos ordenados que resolvem um problema."),
    ("Competências digitais", "Cultura digital", "Uso crítico de informações", "fake news|informações|fontes confiáveis|curadoria|checagem",
     "Avalia a confiabilidade das informações."),
    ("Competências digitais", "Cultura digital", "Produção de conteúdos digitais", "produção digital|mídias digitais|vídeo|podcast|blog|ferramentas digitais",
     "Produz conteúdos usando tecnologias digitais."),
    ("Competências digitais", "Direitos digitais", "Segurança, privacidade e cidadania digital", "dados pessoais|privacidade|segurança|cyberbullying|ética|direitos",
     "Usa tecnologias com segurança, ética e respeito aos dados."),
]

# Itens do eixo Educação Digital Escolar (Lei nº 14.533/2023, art. 3º, incisos I a V),
# texto conferido no Planalto em 31/10/2026.
PNED = [
    ("PNED-I", "Pensamento computacional",
     "pensamento computacional, que se refere à capacidade de compreender, analisar, definir, modelar, resolver, "
     "comparar e automatizar problemas e suas soluções de forma metódica e sistemática, por meio do desenvolvimento "
     "da capacidade de criar e adaptar algoritmos, com aplicação de fundamentos da computação para alavancar e "
     "aprimorar a aprendizagem e o pensamento criativo e crítico nas diversas áreas do conhecimento;",
     "algoritmo|fluxograma|programação|pensamento computacional|automatizar"),
    ("PNED-II", "Mundo digital",
     "mundo digital, que envolve a aprendizagem sobre hardware, como computadores, celulares e tablets, e sobre o "
     "ambiente digital baseado na internet, como sua arquitetura e aplicações;",
     "internet|computador|hardware|ambiente digital"),
    ("PNED-III", "Cultura digital",
     "cultura digital, que envolve aprendizagem destinada à participação consciente e democrática por meio das "
     "tecnologias digitais, o que pressupõe compreensão dos impactos da revolução digital e seus avanços na "
     "sociedade, a construção de atitude crítica, ética e responsável em relação à multiplicidade de ofertas "
     "midiáticas e digitais e os diferentes usos das tecnologias e dos conteúdos disponibilizados;",
     "tecnologias digitais|mídias digitais|digital|redes sociais|mídia|ambientes digitais"),
    ("PNED-IV", "Direitos digitais",
     "direitos digitais, que envolve a conscientização a respeito dos direitos sobre o uso e o tratamento de dados "
     "pessoais, nos termos da Lei nº 13.709, de 14 de agosto de 2018 (Lei Geral de Proteção de Dados Pessoais), a "
     "promoção da conectividade segura e a proteção dos dados da população mais vulnerável, em especial crianças e "
     "adolescentes;",
     "dados pessoais|privacidade|segurança na internet"),
    ("PNED-V", "Tecnologia assistiva",
     "tecnologia assistiva, que engloba produtos, recursos, metodologias, estratégias, práticas e serviços que "
     "objetivam promover a funcionalidade e a aprendizagem, com foco na inclusão de pessoas com deficiência ou "
     "mobilidade reduzida.",
     "tecnologia assistiva"),
]
