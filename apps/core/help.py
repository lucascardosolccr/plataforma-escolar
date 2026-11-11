"""Conteúdo da página de ajuda (/ajuda/), por perfil.

Cada guia diz em passos curtos como fazer uma tarefa real da plataforma.
Os links dos passos só aparecem quando a tela está no menu do perfil
(``navigation.all_visible_urls``): a ajuda nunca aponta para uma página que
o usuário não pode abrir.
"""

from django.urls import NoReverseMatch, reverse

from .models import Role

ADMIN = Role.ADMIN.value
DIRECAO = Role.DIRECAO.value
COORDENACAO = Role.COORDENACAO.value
SECRETARIA = Role.SECRETARIA.value
PROFESSOR = Role.PROFESSOR.value
RESPONSAVEL = Role.RESPONSAVEL.value
ESTUDANTE = Role.ESTUDANTE.value
GESTAO = (DIRECAO, COORDENACAO)
TODOS = (ADMIN, DIRECAO, COORDENACAO, SECRETARIA, PROFESSOR, RESPONSAVEL, ESTUDANTE)

# (título, ícone, perfis, [(texto do passo, url_name ou None)])
GUIDES = [
    # Professor
    ("Fazer a chamada do dia", "calendar-check", (PROFESSOR,), [
        ("Abra Frequência e escolha a turma.", "pedagogy:attendance_list"),
        ("Todos começam como presentes: marque só quem faltou ou chegou atrasado.", None),
        ("Salve. A chamada pode ser corrigida depois na mesma tela.", None),
    ]),
    ("Criar uma avaliação e lançar as notas", "graduation-cap", (PROFESSOR,), [
        ("Em Avaliações e notas, use “Nova avaliação”.", "pedagogy:evaluation_create"),
        ("Depois de salvar, clique em “Notas” na linha da avaliação e preencha.", "pedagogy:evaluation_list"),
        ("Publique quando terminar. Antes de publicar, a família não vê nada.", None),
    ]),
    ("Passar uma atividade de casa", "notebook-pen", (PROFESSOR,), [
        ("Em Atividades de casa, use “Nova atividade”.", "pedagogy:activity_create"),
        ("A prévia ao lado mostra o cartão exatamente como a família vai ver.", None),
        ("Publique agora ou agende uma data: a família é avisada quando a atividade aparece.", None),
        ("Depois do prazo, abra a atividade e registre quem entregou.", "pedagogy:activity_list"),
        ("Editou depois de publicar? A tela da atividade guarda o histórico, e a família vê que ela mudou.", None),
    ]),
    ("Preparar a turma para uma prova", "book-open", (PROFESSOR,), [
        ("Em Conteúdos da prova, use “Novos conteúdos” e escolha a avaliação, se já existir.", "study:create"),
        ("Acrescente os tópicos com as habilidades e os materiais (vídeos, leituras, arquivos).", None),
        ("Publique: a turma e as famílias são avisadas. Responda às dúvidas na própria tela.", None),
        ("“Plano de cada estudante” mostra por onde cada um deve começar e por quê.", "study:list"),
    ]),
    ("Corrigir com rubrica", "list-checks", (PROFESSOR,), [
        ("Em Rubricas, crie critérios e níveis, com o que se espera em cada um.", "pedagogy:rubric_list"),
        ("Escolha a rubrica no formulário da atividade de casa.", None),
        ("Na atividade, “Avaliar com a rubrica”. A família vê só o nível do próprio filho.", None),
    ]),
    ("Estudar para uma prova", "book-open", (ESTUDANTE, RESPONSAVEL), [
        ("Em Minhas provas (família: Conteúdos da prova) estão o que vai cair e o que estudar.", "study:list"),
        ("Siga “Por onde começar”, use os materiais e marque como está em cada tópico.", None),
        ("Dúvida? Envie ao professor na própria prova: a resposta aparece ali.", None),
    ]),
    ("Marcar uma reunião com a família", "users-round", (PROFESSOR, COORDENACAO, DIRECAO, SECRETARIA), [
        ("Em Reuniões, use “Marcar reunião”, escolha o estudante e marque “Convidar os responsáveis”.",
         "meetings:create"),
        ("A família recebe o aviso na plataforma e um lembrete na véspera. A pauta aparece para ela.", None),
        ("Depois da conversa, registre o que foi combinado. Anotações só da equipe vão em campo próprio, "
         "que a família nunca vê.", None),
        ("Encaminhamentos têm responsável e prazo, e aparecem na lista de quem ficou responsável.", None),
    ]),
    ("Simular a média ou a frequência", "sliders-horizontal", TODOS, [
        ("No painel do estudante, use “Simular cenários”.", None),
        ("Digite uma nota hipotética para ver a média, ou quantas faltas, para ver a frequência do ano. "
         "Nada é gravado.", None),
    ]),
    ("Organizar um trabalho em grupo", "users-round", (PROFESSOR,), [
        ("Crie o trabalho em Trabalhos em grupo.", "pedagogy:group_work_create"),
        ("Em “Organizar grupos”, monte os grupos à mão ou sorteie.", "pedagogy:group_work_list"),
        ("Cada família vê só o grupo do próprio filho.", None),
    ]),
    ("Ocorrência ou observação?", "eye", (PROFESSOR, COORDENACAO, DIRECAO), [
        ("Ocorrência: um fato, como um incidente ou um comportamento, com acompanhamento até ser concluído. A família vê.", "pedagogy:occurrence_list"),
        ("Observação pedagógica: registro da aprendizagem (dificuldades, avanços, estratégias). A equipe pedagógica e os responsáveis do estudante veem; secretaria, administração e o próprio estudante não.", "pedagogy:observation_list"),
    ]),
    # Família
    ("Ligar sua conta ao seu filho", "link", (RESPONSAVEL,), [
        ("Em Vínculos, peça o vínculo com o nome completo do estudante, como consta na matrícula, e a sua relação com ele.", "link_request"),
        ("A secretaria confere e aprova. Só depois disso os dados do estudante aparecem.", None),
    ]),
    ("Acompanhar tarefas, notas e frequência", "notebook-pen", (RESPONSAVEL,), [
        ("Atividades de casa mostra o que está para entregar, por filho.", "pedagogy:activity_list"),
        ("Na atividade, “Estou ciente” avisa o professor de que vocês leram. Não marca a tarefa como feita.", None),
        ("Notas mostra só as avaliações que o professor já publicou.", "pedagogy:evaluation_list"),
        ("Frequência mostra presenças, atrasos e faltas.", "pedagogy:attendance_list"),
        ("O painel de cada filho reúne tudo isso com a evolução no tempo.", "my_children"),
    ]),
    ("Justificar uma falta", "file-check", (RESPONSAVEL,), [
        ("Use “Justificar falta” e anexe o atestado, se tiver.", "pedagogy:justification_create"),
        ("A secretaria analisa e responde. A aprovação não muda a chamada sozinha: a escola corrige o registro, se for o caso.", None),
    ]),
    ("Falar com a escola", "message-circle", (RESPONSAVEL,), [
        ("Mensagens: conversa com a escola ou com um professor.", "communication:thread_list"),
        ("Solicitações: pedidos com acompanhamento, como declarações ou reuniões.", "communication:request_list"),
        ("Comunicados: avisos da escola para todas as famílias ou para uma turma.", "communication:announcement_list"),
    ]),
    # Estudante
    ("Ver o que tenho para fazer", "notebook-pen", (ESTUDANTE,), [
        ("A tela Início mostra as próximas entregas.", "home"),
        ("Atividades e Trabalhos têm os detalhes e os anexos.", None),
        ("O Calendário mostra prazos e avaliações por data.", "school_calendar:calendar_index"),
    ]),
    # Secretaria e administração
    ("Cadastrar um estudante e matricular", "id-card", (SECRETARIA, ADMIN), [
        ("Cadastre em Estudantes → “Cadastrar estudante”.", "student_create"),
        ("Matricule em Matrículas → “Nova matrícula”, escolhendo turma e ano letivo.", "enrollment_create"),
        ("Para dar acesso ao estudante, crie a conta pela ficha dele.", "student_list"),
    ]),
    ("Aprovar vínculos de responsáveis", "link", (SECRETARIA, ADMIN), [
        ("Em Vínculos, confira cada pedido com os documentos da escola.", "link_list"),
        ("Só aprove quando tiver certeza: o vínculo dá acesso a notas, frequência e ocorrências.", None),
    ]),
    ("Senha esquecida", "key-round", (SECRETARIA, ADMIN), [
        ("A plataforma não envia e-mail. Abra a ficha da pessoa e gere uma senha temporária.", None),
        ("Entregue a senha pessoalmente. No primeiro acesso, a pessoa é obrigada a trocá-la.", None),
    ]),
    ("Criar contas da equipe", "user-cog", (ADMIN,), [
        ("Em Usuários, use “Criar conta profissional” e escolha o perfil.", "user_create"),
        ("O perfil define o menu e o que a pessoa pode ver; o vínculo com turmas vem das atribuições.", "assignment_list"),
    ]),
    # Gestão
    ("Ler os painéis de análise", "chart-column", GESTAO + (PROFESSOR, SECRETARIA, ADMIN), [
        ("Escolha o período no topo do painel. Os números comparam com o período anterior.", None),
        ("O “i” ao lado de cada indicador explica o cálculo, a fonte e os limites.", "analytics:methodology"),
        ("“—” significa que não há registro, não que o valor é zero.", None),
        ("Clique numa barra para ver os registros que formam o número.", None),
    ]),
    ("Acompanhar um estudante com dificuldade", "heart-handshake", GESTAO, [
        ("Abra o painel do estudante pela ficha ou pela busca (Ctrl+K).", "student_list"),
        ("Registre um plano de acompanhamento com objetivo e prazo.", "pedagogy:plan_create"),
        ("O painel compara os 60 dias antes e depois do início do plano.", None),
    ]),
    ("Conferir se os dados estão completos", "check", GESTAO + (SECRETARIA, ADMIN), [
        ("Qualidade dos dados lista chamadas, notas e entregas que faltam lançar.", "analytics:data_quality"),
    ]),
    # Prompt 14
    ("Ver o que falta resolver", "list-checks", (PROFESSOR, SECRETARIA, COORDENACAO, DIRECAO, ADMIN, RESPONSAVEL), [
        ("Pendências junta, de várias telas, o que está esperando por você.", "pending_center"),
        ("Cada item leva direto à tela onde se resolve.", None),
    ]),
    ("Importar estudantes por planilha", "file-text", (SECRETARIA, ADMIN), [
        ("Baixe o modelo em Importar estudantes e preencha a aba “Alunos”.", "student_import"),
        ("Envie o arquivo e confira a prévia: cada linha diz se é novo, já cadastrado ou tem erro.", None),
        ("Escolha “só novos” ou “atualizar” (atualizar pede confirmação) e importe.", None),
        ("Baixe as linhas com erro, corrija e envie de novo: quem já entrou não duplica.", None),
        ("Fotos: envie em lote com o código do aluno no nome do arquivo.", "student_photo_batch"),
    ]),
    ("Rematricular para o ano seguinte", "layers", (SECRETARIA, ADMIN), [
        ("Cadastre o novo ano letivo e as turmas dele.", "school_year_list"),
        ("Em Matrículas, abra Rematrícula em lote e escolha a turma de origem.", "enrollment_rollover"),
        ("Desmarque quem fica retido ou sai, escolha a turma de destino e confirme.", None),
        ("Os retidos são rematriculados depois, em outra turma de destino.", None),
        ("Ao começar as aulas, marque o novo ano como atual em Anos letivos.", "school_year_list"),
    ]),
    ("Analisar pré-cadastros das famílias", "id-card", (SECRETARIA, ADMIN), [
        ("Abra Pré-cadastros e escolha um pedido enviado.", "application_review_list"),
        ("Aprove (cria a ficha e o vínculo), peça correção ou recuse, sempre com mensagem.", None),
        ("Matrícula só se você escolher a turma; dá para matricular depois.", None),
        ("O que a família pode fazer, e para quais anos letivos, é definido em Cadastro pelas famílias.",
         "registration_settings"),
        ("Com mais de um ano aberto, a família escolhe o ano; as turmas oferecidas na aprovação são desse ano.",
         None),
    ]),
    ("Cobrar fotos pendentes", "user-round", (SECRETARIA, DIRECAO, ADMIN), [
        ("Fotografias lista quem ainda não tem foto, por turma.", "photo_pending"),
        ("Marque os estudantes e use “Cobrar as famílias”: elas recebem um aviso.", None),
        ("Dispensa com justificativa é registrada pela direção ou administração.", None),
    ]),
    ("Cadastrar o calendário oficial", "calendar-check", (SECRETARIA, DIRECAO, ADMIN), [
        ("Confira início e fim do ano letivo.", "school_year_list"),
        ("Em Calendário oficial, inclua bimestres, feriados, recessos e férias.", "school_calendar:official"),
        ("Publique: só então a contagem de dias letivos aparece para todos.", None),
    ]),
    ("Publicar o cardápio e os horários", "heart-handshake", (SECRETARIA, DIRECAO, ADMIN), [
        ("Em Cardápio, edite o dia ou copie a semana anterior.", "rotina:menu"),
        ("Ingredientes e alergênicos só aparecem com o nome de quem validou.", None),
        ("Horários: escolha a turma e inclua as aulas; conflitos são avisados.", "rotina:schedule_index"),
    ]),
    ("Planejar as aulas", "clipboard-check", (PROFESSOR,), [
        ("Em Planejamento, crie o plano da semana (ou do período) por turma e disciplina.", "pedagogy:lessonplan_list"),
        ("Fica como rascunho até você enviar para a coordenação.", None),
        ("Se voltar para ajustes, a orientação aparece no plano: corrija e envie de novo.", None),
        ("“Copiar para o próximo período” poupa digitação quando o plano continua.", None),
    ]),
    ("Acompanhar o planejamento docente", "clipboard-check", (COORDENACAO, DIRECAO), [
        ("Em Planejamento, os planos enviados das turmas que você acompanha esperam devolutiva.",
         "pedagogy:lessonplan_list"),
        ("Valide ou devolva para ajustes; devolver pede uma orientação, que o professor recebe.", None),
        ("O painel da coordenação mostra quais turmas e disciplinas estão sem plano nesta semana.",
         "coordination:panel"),
    ]),
    ("Reaproveitar uma atividade", "history", (PROFESSOR,), [
        ("Em Atividades de casa, abra Minhas atividades anteriores (de qualquer turma ou ano).",
         "pedagogy:activity_bank"),
        ("Clique em Reutilizar, escolha a turma atual e a data de aplicação.", None),
        ("Sai um rascunho com o texto e os anexos: revise e publique.", None),
    ]),
    ("Pedir a impressão de uma atividade", "printer", (PROFESSOR,), [
        ("Em Atividades e impressões, escolha a atividade e “Pedir impressão”.", "printing:mine"),
        ("Confira a data de aplicação, a data desejada e as cópias (sugeridas pela turma).", None),
        ("Envie: a coordenação analisa e você acompanha cada passo e o histórico.", None),
    ]),
    ("Analisar pedidos de impressão", "printer", (COORDENACAO, DIRECAO), [
        ("A Fila de impressão mostra os pedidos das suas turmas por data.", "printing:queue"),
        ("Aprove, peça correção ou recuse; correção e recusa pedem justificativa.", None),
    ]),
    ("Imprimir e entregar", "printer", (SECRETARIA, ADMIN), [
        ("Em Fila de impressão, “Para imprimir e entregar”.", "printing:queue"),
        ("Registre cada passo: em impressão, impressa, disponível, entregue. O professor é avisado.", None),
    ]),
    ("Acompanhar como coordenação", "layout-dashboard", (COORDENACAO,), [
        ("O Painel da coordenação mostra só as turmas da sua designação.", "coordination:panel"),
        ("Registre orientações e reuniões em Registros da coordenação.", "coordination:records"),
    ]),
    ("Designar a coordenação e dar acesso extra a professores", "user-cog", (DIRECAO, ADMIN), [
        ("Em Designação da coordenação, escolha turmas, disciplinas ou professores.", "coordination:designations"),
        ("Professor vê só as disciplinas dele; acesso extra, com prazo, em Permissões de professores.",
         "teacher_permissions"),
        ("Avisos automáticos: escolha quais registros avisam a família.", "communication:notification_rules"),
    ]),
    ("Pré-cadastrar um filho", "id-card", (RESPONSAVEL,), [
        ("Quando a escola abre o cadastro, aparece Pré-cadastro no menu.", "family_applications"),
        ("Preencha em etapas; dá para salvar e continuar depois.", None),
        ("A secretaria confere e avisa você aqui na plataforma.", None),
    ]),
    # Prompt 15
    ("Divulgar a data de uma prova", "clipboard-check", (PROFESSOR,), [
        ("Ao criar a avaliação, deixe marcado “divulgar a data para a turma”.", "pedagogy:evaluation_create"),
        ("A prova entra na agenda do estudante e da família, e os lembretes saem com a antecedência definida pela escola.", None),
        ("Mudou a data ou desmarcou? Salve a avaliação: todos recebem o aviso e os lembretes antigos ficam como resolvidos.", None),
    ]),
    ("Relacionar habilidades da BNCC", "book-marked", (PROFESSOR,), [
        ("Na atividade, no trabalho, na avaliação ou no planejamento, marque as habilidades na seção “Habilidades e objetivos curriculares”.", "pedagogy:activity_create"),
        ("O filtro aceita código (EF06MA03) ou palavra (frações). Outros códigos podem ser digitados.", None),
        ("Registre evidências da turma e acompanhe o que foi previsto, trabalhado e avaliado.", "curriculum:coverage"),
    ]),
    ("Ver as orientações de apoio dos estudantes", "heart-handshake", (PROFESSOR,), [
        ("Em Orientações de apoio aparecem recursos, estratégias e cuidados definidos pela equipe pedagógica.", "inclusion:guidance"),
        ("Diagnóstico e laudo não aparecem: as orientações dizem o que fazer em sala.", None),
    ]),
    ("Acompanhar a inclusão de um estudante", "heart-handshake", GESTAO, [
        ("Em Apoio à inclusão, abra a ficha do estudante (ou pela ficha cadastral, aba Pedagógico).", "inclusion:overview"),
        ("Analise documentos, peça complementação à família e registre necessidades de apoio, com ou sem laudo.", None),
        ("Elabore o plano individualizado (PAEE e PEI em documento único) a partir do estudo de caso e revise em até um ano.", None),
        ("Indicadores agregados, sem diagnóstico, ficam em Indicadores.", "inclusion:panel"),
    ]),
    ("Informar à escola uma necessidade específica", "heart-handshake", (RESPONSAVEL,), [
        ("Em Necessidades e laudos, abra a ficha do seu filho e use “Informar ou atualizar”.", "inclusion:overview"),
        ("Laudo não é obrigatório. Se tiver, anexe em PDF, JPG ou PNG.", None),
        ("Acompanhe a análise e responda aos pedidos de complementação pela mesma tela.", None),
    ]),
    ("Definir a antecedência dos lembretes", "bell", (DIRECAO, ADMIN), [
        ("Em Avisos automáticos, ajuste os dias antes da entrega, depois do vencimento e antes das provas.", "communication:notification_rules"),
        ("O quadro de processamentos mostra quando os lembretes rodaram e quantos avisos saíram.", None),
    ]),
    # Prompt 16 — EIA-Cognitio
    ("Acompanhar a aprendizagem por habilidade", "chart-line", (PROFESSOR,), [
        ("Na avaliação, use “Questões” e ligue cada questão à habilidade que ela verifica.", "pedagogy:evaluation_list"),
        ("Lance os resultados por questão. Em branco, ausente ou não aplicada não contam como dificuldade.", None),
        ("Veja o mapa da turma e o de cada estudante no EIA-Cognitio.", "cognitio:home"),
        ("Revise os alertas: cada um diz por que foi gerado. Descartar exige um motivo.", "cognitio:alerts"),
    ]),
    ("Planejar uma intervenção ou uma trilha", "heart-handshake", (PROFESSOR,), [
        ("No mapa da turma, toque numa habilidade e use “Planejar intervenção” ou “Gerar trilha”.", "cognitio:home"),
        ("As estratégias sugeridas mostram as razões e o respaldo. A decisão é sua.", "cognitio:strategies"),
        ("Depois do início, a intervenção mostra se as evidências melhoraram (acompanhamento, não prova de efeito).",
         "cognitio:interventions"),
    ]),
    ("Validar o grafo e os modelos do EIA-Cognitio", "chart-line", GESTAO, [
        ("Na página de uma habilidade, valide ou rejeite pré-requisitos e dimensões propostos.", "curriculum:catalog"),
        ("Em Modelos e validação, acompanhe as regras de alerta e execute a validação do modelo.", "cognitio:models"),
        ("Nenhuma probabilidade aparece sem modelo validado e aprovado pela direção.", None),
    ]),
    ("Definir e acompanhar metas da escola", "flag", GESTAO, [
        ("Em Metas da escola, a direção cadastra um indicador (frequência, média, entregas ou habilidades), "
         "o valor-alvo e o prazo, para a escola toda ou para uma turma.", "analytics:goals"),
        ("O resultado é calculado pela plataforma, com as fórmulas do painel institucional, do início da meta "
         "até hoje. Ninguém digita o resultado.", None),
        ("No painel institucional, o botão Metas da escola mostra quantas estão no alvo.",
         "analytics:institutional_dashboard"),
    ]),
    ("Conferir o Currículo em Movimento do DF", "list-checks", GESTAO, [
        ("Em Currículo → Importar, traga o Currículo em Movimento (já incluído na plataforma). Os itens chegam "
         "marcados \"texto a conferir\".", "curriculum:item_import"),
        ("Em Curadoria, leia lado a lado o objetivo e a habilidade sugerida; marque vários e valide ou rejeite. "
         "Comece pela confiança média: são textos quase iguais.", "curriculum:curation"),
        ("Na página de cada item, confira o texto com o documento oficial (a página do PDF aparece na fonte) e "
         "use \"Marcar como conferido\"; dá para corrigir a extração, e a redação anterior fica guardada.",
         "curriculum:catalog"),
    ]),
    ("Escolher que avisos receber", "bell", (RESPONSAVEL, PROFESSOR, ESTUDANTE), [
        ("Em Notificações, abra Preferências e desmarque o que não quer receber.",
         "communication:notification_preferences"),
        ("Avisos de ocorrência e de vínculo sempre chegam.", None),
    ]),
    # Carteirinha e portaria
    ("Emitir e imprimir as carteirinhas", "id-card", (SECRETARIA, DIRECAO, ADMIN), [
        ("Em Carteirinhas, abra a turma e use “Emitir as que faltam”.", "gate:cards"),
        ("Cadastre a foto antes: sem foto, a carteirinha sai com as iniciais e a portaria não confere o rosto.",
         "photo_pending"),
        ("Use “Imprimir a turma”, em tamanho real (100%). Recorte frente e verso, cole e plastifique.", None),
        ("Perdeu? Na carteirinha do estudante, “Emitir segunda via” com o motivo: a anterior deixa de valer.", None),
    ]),
    ("Registrar a entrada e a saída na portaria", "id-card", (SECRETARIA, COORDENACAO, DIRECAO, ADMIN), [
        ("Abra Portaria e escolha Entrada ou Saída.", "gate:station"),
        ("Leia a carteirinha com o leitor (QR Code ou código de barras) ou digite o código de 9 caracteres.", None),
        ("Confira a foto que aparece. Sem carteirinha, busque o nome em “Sem carteirinha”.", None),
        ("Em Portaria hoje, veja quem chegou, quem atrasou e quem ainda não chegou, por turma.", "gate:today"),
    ]),
    ("Definir o horário de entrada e a tolerância de atraso", "clock", (DIRECAO, ADMIN), [
        ("Em Portaria hoje, abra “Horários e tolerância”.", "gate:today"),
        ("Cada turma usa o horário do seu turno. Depois do horário mais a tolerância, a chegada vira atraso e a "
         "família é avisada.", None),
    ]),
    ("Ver a carteirinha e os horários de chegada", "id-card", (RESPONSAVEL, ESTUDANTE), [
        ("Em Carteirinha e entradas, abra a carteirinha: dá para mostrá-la no celular na entrada.", "gate:mine"),
        ("Ali também ficam as entradas, as saídas e os atrasos. Os avisos de chegada podem ser silenciados em "
         "Notificações → Preferências.", None),
    ]),
    # Autorizações assinadas
    ("Assinar uma autorização de passeio", "file-check", (RESPONSAVEL,), [
        ("Em Autorizações, abra a atividade e use “Ler e assinar” no nome do seu filho.",
         "communication:authorization_list"),
        ("Leia o texto, escolha a resposta, digite o seu nome completo e a sua senha. A senha é pedida de novo para "
         "que ninguém assine pela sua conta aberta.", None),
        ("Você e os outros responsáveis recebem o comprovante com um código. Recebeu um comprovante que não "
         "assinou? Avise a escola e troque a senha.", None),
    ]),
    ("Conferir as assinaturas de um passeio", "shield", (PROFESSOR, COORDENACAO, DIRECAO, SECRETARIA, ADMIN), [
        ("Na autorização, a coluna Comprovante mostra o código de cada assinatura e avisa se algum registro foi "
         "alterado ou se a família assinou uma versão anterior do texto.", "communication:authorization_list"),
        ("Para conferir um papel ou um print, use “Conferir comprovante” e digite o código.",
         "communication:authorization_verify"),
        ("“Lembrar quem não respondeu” avisa só as famílias que faltam (uma vez por dia). A lista impressa traz os "
         "códigos, os alertas de saúde e o contato de emergência de cada autorizado.", None),
    ]),
    ("Pedir autorização de uso de imagem ou de saída sozinho(a)", "camera",
     (PROFESSOR, COORDENACAO, DIRECAO, SECRETARIA, ADMIN), [
        ("Em Autorizações → Nova autorização, escolha o tipo “Uso de imagem e voz” ou “Sair sozinho(a) da escola” "
         "e diga até quando vale (ex.: fim do ano letivo). No texto, explique onde as fotos aparecem.",
         "communication:authorization_create"),
        ("Antes de publicar foto ou vídeo, abra “Quem pode aparecer em fotos”: só aparece quem tem assinatura "
         "válida hoje. Sem resposta é o mesmo que não autorizado.", "communication:authorization_images"),
        ("Na saída, a portaria vê a opção “Sai sozinho(a)” só para quem tem a autorização assinada e válida. A "
         "família pode retirar a autorização a qualquer momento, e quem criou e a direção são avisados.", None),
    ]),
    ("Retirar uma autorização de uso de imagem ou de saída sozinho(a)", "camera", (RESPONSAVEL,), [
        ("Em Autorizações, abra a autorização e use “Retirar a autorização” (ou “Mudar a resposta”, dentro do "
         "prazo). Vale na hora e a escola é avisada.", "communication:authorization_list"),
    ]),
    # Biblioteca escolar
    ("Emprestar e receber livros da biblioteca", "book-open", (DIRECAO, COORDENACAO, SECRETARIA, ADMIN), [
        ("Cadastre o acervo em Biblioteca escolar → Cadastrar livro, ou importe a planilha (CSV) pelo Balcão.",
         "library:catalog"),
        ("Para emprestar, abra o livro, use “Emprestar” e procure o estudante pelo nome ou pelo código. A data de "
         "devolução sai sozinha (próximo dia letivo, se cair sem aula) e a família recebe o aviso.", None),
        ("No Balcão ficam os livros emprestados, com os atrasados primeiro. Lembrete na véspera e aviso de atraso "
         "saem sozinhos. Professores também podem operar o balcão: marque-os em Regras.", "library:desk"),
    ]),
    ("Livros da biblioteca: empréstimos e reservas", "book-open", (RESPONSAVEL, ESTUDANTE), [
        ("Em Biblioteca escolar → Meus livros: o que está emprestado, até quando, e o que já foi lido.",
         "library:mine"),
        ("Livro sem exemplar livre? Abra e use “Entrar na fila”. Quando ele voltar, avisamos e ele fica separado "
         "por alguns dias. Dá para renovar pela plataforma se ninguém estiver esperando.", "library:catalog"),
    ]),
    # Achados e perdidos
    ("Registrar e entregar achados e perdidos", "package", (PROFESSOR, COORDENACAO, DIRECAO, SECRETARIA, ADMIN), [
        ("Em Achados e perdidos → Registrar objeto: o que é, onde foi achado e, se quiser, uma foto só do objeto.",
         "lostfound:create"),
        ("Tem nome escrito? No objeto, procure o estudante: a família é avisada na hora.", None),
        ("Quando a família diz “é meu”, confira a descrição antes de entregar. Depois de 60 dias, os objetos "
         "guardados podem ser marcados como doados; as fotos são apagadas.", "lostfound:list"),
    ]),
    # Atendimentos de saúde
    ("Registrar um atendimento de saúde", "heart-handshake", (PROFESSOR, COORDENACAO, DIRECAO, SECRETARIA, ADMIN), [
        ("Numa emergência, socorra e ligue primeiro. Depois, em Saúde e retirada → Registrar atendimento: o que "
         "aconteceu, o que foi feito e o desfecho. A ficha de saúde aparece junto.", "care:incident_pick"),
        ("A família recebe um aviso importante na hora (com orientações se bateu a cabeça) e marca ciente.",
         "care:incidents"),
    ]),
    ("Ver os atendimentos de saúde do seu filho", "heart-handshake", (RESPONSAVEL,), [
        ("Em Saúde e retirada → Atendimentos na escola: o que aconteceu, o que a escola fez e o desfecho. Marque "
         "“Estou ciente” e, se quiser, deixe um recado.", "care:incidents"),
    ]),
    ("Dar remédio na escola", "heart-handshake", (SECRETARIA, DIRECAO, ADMIN, COORDENACAO), [
        ("A família pede em Saúde e retirada → Remédio na escola e entrega a receita e o remédio. A secretaria, "
         "a direção ou a administração confere e autoriza (ou não, com o motivo).", "care:medications"),
        ("Em Remédios de hoje aparecem os horários do dia, com as alergias da ficha. Registre cada um: tomou, não "
         "quis, não estava na escola ou não foi dado. A família recebe um aviso a cada registro. Errou? Quem "
         "registrou desfaz em até 10 minutos.", "care:medication_today"),
    ]),
    ("Pedir para a escola dar um remédio", "heart-handshake", (RESPONSAVEL,), [
        ("Em Saúde e retirada → Remédio na escola: remédio, dose, horários de aula, período e a receita. Entregue "
         "a receita e o remédio na secretaria; a escola só dá depois de conferir.", "care:medications"),
        ("A cada dose você recebe um aviso (também quando não foi dado). Para parar, use “Encerrar”.", None),
    ]),
    ("Abrir horários para as famílias marcarem", "clock", (PROFESSOR, COORDENACAO, DIRECAO, SECRETARIA), [
        ("Em Horários de atendimento → Abrir horários: assunto, dia, das/até, quanto dura cada conversa e as "
         "turmas. As famílias dessas turmas recebem um aviso.", "office:create"),
        ("Cada horário marcado vira uma reunião com você e os responsáveis, com lembrete na véspera e espaço "
         "para o registro. “Liberar” cancela e avisa a família; “Fechar marcações” para de aceitar novas.",
         "office:list"),
    ]),
    ("Marcar uma conversa com o professor", "clock", (RESPONSAVEL,), [
        ("Em Horários de atendimento aparecem os horários abertos para a turma do seu filho. Escolha um livre "
         "e diga o assunto, se quiser. Dá para desmarcar até a hora.", "office:list"),
    ]),
    ("Controlar os documentos da matrícula", "file-check", (SECRETARIA, DIRECAO, ADMIN), [
        ("Em Documentos da matrícula → Lista de documentos, ajuste o que a escola pede (já vem uma lista "
         "inicial). Os obrigatórios contam como pendência.", "paperwork:settings"),
        ("Abra a turma e marque o que cada estudante entregou; “Salvar a turma” grava tudo de uma vez. Para "
         "outra data ou para dispensar (com o motivo), abra o estudante.", "paperwork:index"),
        ("“Lembrar as famílias” manda a cada família a lista do que falta. A planilha traz os pendentes.", None),
    ]),
    ("Ver os documentos que faltam entregar", "file-check", (RESPONSAVEL,), [
        ("Em Documentos da matrícula aparece, por filho, o que a secretaria já recebeu e o que falta.",
         "paperwork:index"),
    ]),
    ("Abrir uma oficina com inscrição", "star", (PROFESSOR, COORDENACAO, DIRECAO, SECRETARIA, ADMIN), [
        ("Em Oficinas → Nova oficina: nome, dias e horário, período, vagas, prazo de inscrição e as turmas. "
         "Salve, confira e publique: as famílias das turmas recebem um aviso.", "workshops:create"),
        ("Com as vagas cheias, a inscrição vai para a lista de espera. Quando alguém desiste (ou você aumenta as "
         "vagas), o primeiro da fila é chamado e a família avisada. “Lista de presença” imprime os inscritos.",
         "workshops:index"),
    ]),
    ("Inscrever seu filho numa oficina", "star", (RESPONSAVEL,), [
        ("Em Oficinas aparecem as abertas para a turma do seu filho. Inscreva até o prazo; se estiver cheia, ele "
         "entra na lista de espera e você recebe um aviso se abrir vaga. Cancele se não puder participar.",
         "workshops:index"),
    ]),
    ("Lançar os anos anteriores de um estudante", "history", (SECRETARIA, DIRECAO, ADMIN), [
        ("Em Trajetória escolar → Importar anos anteriores, envie a planilha (modelo na própria tela): uma linha "
         "por estudante e ano, com série, escola, resultado, frequência e as notas finais. Confira e confirme.",
         "longitudinal:import"),
        ("Para um estudante só: ficha → Trajetória escolar → Lançar ano anterior. No fim do ano, lance o "
         "resultado final de cada turma em Trajetória escolar → Resultados do ano.", "longitudinal:index"),
    ]),
    ("Ler a trajetória e a previsão", "history", (DIRECAO, COORDENACAO), [
        ("Em Trajetória escolar aparecem, no começo do ano, os estudantes que chegam com sinais (retenção, "
         "distorção idade-série, ausência crônica, dificuldade persistente) e a validação de cada sinal com os "
         "dados da própria escola.", "longitudinal:index"),
        ("A previsão só aparece depois de validada com os dados da escola e aprovada pela direção em "
         "Trajetória escolar → Previsão. Família e estudante não a veem.", "longitudinal:model"),
    ]),
    # Rematrícula
    ("Confirmar a rematrícula com as famílias", "calendar-check", (SECRETARIA, DIRECAO, ADMIN), [
        ("Crie o ano letivo seguinte em Acadêmico → Anos letivos e abra a campanha em Confirmação de "
         "rematrícula: prazo, orientações, turmas e, se quiser, um termo de aceite.", "reenroll:create"),
        ("As famílias recebem um aviso importante e um lembrete perto do prazo. Quem não tem conta responde na "
         "secretaria: use “Registrar no balcão”.", "reenroll:index"),
        ("Na Rematrícula em lote, quem disse que não continua já vem desmarcado.", "enrollment_rollover"),
    ]),
    ("Responder a rematrícula", "calendar-check", (RESPONSAVEL,), [
        ("Em Confirmação de rematrícula, diga se cada filho continua no ano que vem e confira os dados de "
         "contato. Dá para mudar até o prazo; guarde o código do comprovante.", "reenroll:index"),
    ]),
    # Lista de materiais
    ("Montar e publicar a lista de materiais", "list-checks", (PROFESSOR, COORDENACAO, DIRECAO, SECRETARIA, ADMIN), [
        ("Em Lista de materiais → Nova lista: título, ano letivo, série e as turmas que vão usar.", "supplies:create"),
        ("Inclua os materiais um a um ou cole a lista inteira (uma linha por material, quantidade no começo). "
         "A plataforma avisa quando um item é de uso coletivo ou exige marca, o que a lei não permite.", None),
        ("O professor envia para a coordenação; a coordenação, a direção ou a secretaria publica (ou devolve com "
         "observação). Publicada, as famílias das turmas recebem o aviso. “Copiar para outra série” "
         "reaproveita a lista.", "supplies:index"),
    ]),
    ("Ver a lista de materiais", "list-checks", (RESPONSAVEL, ESTUDANTE), [
        ("Em Lista de materiais aparece a lista da turma de cada filho, e também as das outras séries.",
         "supplies:index"),
        ("Marque o que já providenciou (a escola não vê), imprima ou use “Texto” para mandar por mensagem.", None),
    ]),
    ("Procurar um objeto perdido na escola", "package", (RESPONSAVEL, ESTUDANTE), [
        ("Em Achados e perdidos aparece o que foi encontrado nos últimos 90 dias.", "lostfound:list"),
        ("Reconheceu? Abra e use “É meu”, com um detalhe que só o dono sabe. A escola confere e avisa. Celular, "
         "fone, documento e chave aparecem só pelo tipo: descreva o seu.", None),
    ]),
    # Saúde e retirada
    ("Preencher a ficha de saúde e dizer quem pode buscar", "user-check", (RESPONSAVEL,), [
        ("Em Saúde e retirada, use “Preencher a ficha de saúde”: alergias, alimentação, remédios, o que fazer "
         "numa crise e contatos de emergência.", "care:home"),
        ("Em “Quem pode buscar”, inclua avós, tios ou o transporte escolar, com o documento que a portaria vai "
         "conferir. Os responsáveis com vínculo sempre podem.", None),
        ("Vai buscar mais cedo? Use “Avisar saída antecipada”: a portaria vê o aviso no dia.", None),
    ]),
    ("Registrar a retirada de um estudante", "user-check", (SECRETARIA, COORDENACAO, DIRECAO, ADMIN), [
        ("Em Saúde e retirada (ou em Portaria hoje), veja as saídas avisadas e busque o estudante.", "care:home"),
        ("Escolha quem está buscando e confira o documento. A família recebe o aviso com o horário e o nome.", None),
        ("Pessoa fora da lista: só libere depois de falar com um responsável, e escreva com quem falou. A família "
         "recebe um aviso importante.", None),
    ]),
    ("Ver os alertas de saúde da turma", "user-check", (PROFESSOR, COORDENACAO, DIRECAO, SECRETARIA), [
        ("Em Saúde e retirada, abra a turma: alergias, alimentação, condições e o que fazer numa crise.",
         "care:home"),
        ("É dado de saúde de criança: use só para o cuidado em sala e não compartilhe a lista.", None),
    ]),
    # Reservas
    ("Reservar a sala de informática, a quadra ou um equipamento", "calendar-check",
     (PROFESSOR, COORDENACAO, DIRECAO, SECRETARIA), [
        ("Em Reservas, escolha o dia e veja o que está livre.", "booking:agenda"),
        ("Use “Reservar” na linha do espaço, com o horário e, se quiser, a turma. Horário ocupado é recusado com "
         "o nome de quem reservou.", None),
        ("Mudou de ideia? Cancele em “Minhas próximas reservas”.", None),
    ]),
    ("Cadastrar os espaços e equipamentos que podem ser reservados", "settings",
     (DIRECAO, COORDENACAO, SECRETARIA, ADMIN), [
        ("Em Reservas, abra “Espaços e equipamentos” e cadastre cada um (três projetores são três itens).",
         "booking:resources"),
        ("Para manutenção, desmarque “disponível para reserva”.", None),
    ]),
    # Dados pessoais e indicadores
    ("Pedir acesso, correção ou eliminação de dados pessoais (LGPD)", "shield", (RESPONSAVEL,), [
        ("Em Solicitações, use “Pedido sobre dados pessoais” e escolha o que você quer.",
         "communication:request_list"),
        ("A escola tem 15 dias como prazo de referência e responde por ali. O contato do encarregado de dados "
         "está na página Privacidade, no rodapé.", None),
    ]),
    ("Responder um pedido sobre dados pessoais", "shield", (DIRECAO, SECRETARIA, ADMIN), [
        ("Em Solicitações, filtre por “Dados pessoais (LGPD)”: o prazo aparece em cada pedido.",
         "communication:request_list"),
        ("A direção abre “O que a plataforma guarda sobre o estudante” para responder a pedidos de acesso. Antes "
         "de entregar, retire o que identifica outras pessoas.", None),
    ]),
    ("Acompanhar a trajetória e os sinais precoces", "chart-line", (PROFESSOR, COORDENACAO, DIRECAO), [
        ("No EIA-Cognitio, abra a turma e use “Trajetórias e sinais precoces”.", "cognitio:home"),
        ("Cada estudante mostra os indicadores acesos (frequência, comportamento, desempenho, entregas, "
         "trajetória em queda, atrasos) e a tendência por disciplina.", None),
        ("Indicador aceso pede conversa e observação, não rótulo. Professores e coordenação recebem um resumo "
         "semanal com os sinais novos.", None),
    ]),
]

# Perguntas comuns a todos os perfis: (pergunta, resposta, perfis)
FAQ = [
    ("A escola avisa quando o prazo de uma atividade ou a data de uma prova está chegando?",
     "Sim, se a escola deixar ligado. A antecedência é definida pela escola (por exemplo, 3 dias antes, na véspera e no dia). Quem já tem entrega registrada não recebe lembrete, e cada lembrete sai uma vez só. Se o professor mudar a data, você é avisado e os lembretes antigos aparecem como resolvidos. Para não receber, desmarque o tipo em Notificações → Preferências.",
     (RESPONSAVEL, ESTUDANTE)),
    ("Quem vê o laudo que eu enviar?",
     "A coordenação que acompanha a turma e a direção. Os professores veem só as orientações de sala de aula, sem diagnóstico nem laudo; a secretaria vê só a situação da documentação. Cada consulta e cada download ficam registrados. Laudo não é obrigatório para matrícula nem para atendimento.",
     (RESPONSAVEL,)),
    ("Quando a escola precisa avisar o Conselho Tutelar sobre faltas?",
     "Quando o estudante passa de 30% do percentual de faltas permitido em lei (LDB, art. 12, VIII): em 200 dias "
     "letivos, mais de 15 faltas. Em Busca ativa, a plataforma lista quem passou do limite e quem está perto. "
     "Antes de notificar, registre os contatos com a família, porque o ECA (art. 56, II) pede que a escola esgote "
     "os próprios recursos. A notificação também se registra lá, com a data. Nada é enviado automaticamente.",
     (DIRECAO, COORDENACAO, SECRETARIA)),
    ("O EIA-Cognitio decide algo sobre o estudante?",
     "Não. Ele mostra evidências, sinaliza por regras explícitas e sugere estratégias. Nada reprova, classifica ou "
     "restringe direitos; laudos e diagnósticos nunca entram nos alertas. Quem interpreta e decide é o professor.",
     GESTAO + (PROFESSOR,)),
    ("As habilidades da BNCC da plataforma são confiáveis?",
     "As competências gerais e as habilidades do Ensino Fundamental foram carregadas do PDF oficial da BNCC (MEC), sem reescrita. Os objetivos do Currículo em Movimento do DF são cadastrados pela escola, com a fonte.",
     GESTAO + (PROFESSOR,)),
    ("Por que só vejo algumas disciplinas?",
     "Cada professor vê as disciplinas atribuídas a ele. Acesso a outra disciplina é concedido pela direção, secretaria ou administração, com prazo.",
     (PROFESSOR,)),
    ("A foto é obrigatória? Ela é usada para reconhecimento facial?",
     "A foto é uma pendência cadastral, mas nunca bloqueia nada. Serve só para identificação visual: a plataforma não faz reconhecimento facial nem biometria, e a foto é gravada sem a localização do celular.",
     TODOS),
    ("Como encontro uma tela ou um estudante rapidamente?",
     "Aperte Ctrl+K (ou /) e digite. A busca mostra páginas, ações e, para a equipe, estudantes e turmas.", TODOS),
    ("Posso deixar uma página mais à mão?",
     "Sim. A estrela na barra superior guarda a página nos Favoritos, no topo do menu. Favoritos e filtros salvos (o funil ao lado da estrela, numa lista filtrada) ficam na sua conta e aparecem em qualquer computador.", TODOS),
    ("Como sei onde estou?",
     "A trilha no topo (Início / seção / página) mostra o caminho. Clique num nível para voltar a ele.", TODOS),
    # Quem redefine é regra de passwords.can_reset_password: a secretaria só
    # cuida de contas de família (e do acesso do estudante, pela ficha).
    ("Esqueci minha senha.",
     "Se você gerou seus códigos de recuperação (Alterar senha → Códigos de recuperação), use “Esqueci minha senha” na tela de entrada: usuário, um código e a senha nova, sem depender de ninguém. Sem códigos, procure a secretaria da escola: ela gera uma senha temporária, que você troca no primeiro acesso.",
     (RESPONSAVEL, ESTUDANTE)),
    ("Esqueci minha senha.",
     "Se você gerou seus códigos de recuperação (Alterar senha → Códigos de recuperação), use “Esqueci minha senha” na tela de entrada: usuário, um código e a senha nova, sem depender de ninguém. Sem códigos, peça à administração da escola: ela gera uma senha temporária, que você troca no primeiro acesso. "
     "A secretaria só redefine senhas de famílias.",
     GESTAO + (SECRETARIA, PROFESSOR)),
    ("Esqueci minha senha.",
     "Se você gerou seus códigos de recuperação (Alterar senha → Códigos de recuperação), use “Esqueci minha senha” na tela de entrada: usuário, um código e a senha nova, sem depender de ninguém. Sem códigos, outra conta da administração da escola gera uma senha temporária. Se não houver outra, quem instalou a "
     "plataforma pode definir uma nova pelo comando changepassword.",
     (ADMIN,)),
    ("Quem vê os dados do meu filho?",
     "Só a equipe da escola, conforme a função, e os responsáveis com vínculo aprovado. As observações pedagógicas ficam com a equipe pedagógica e com vocês: a secretaria e a administração não as veem.",
     (RESPONSAVEL,)),
    ("Como atualizo meu telefone ou o contato de emergência?",
     "No seu nome, no canto superior direito, abra “Meus dados de contato”. A escola usa esses dados numa emergência.",
     (RESPONSAVEL,)),
    ("Por que uma nota não aparece?",
     "O professor ainda não publicou a avaliação. Enquanto está em rascunho, só ele vê.", (RESPONSAVEL, ESTUDANTE)),
    ("A família vê o que eu escrevo na observação pedagógica?",
     "Só se você marcar “compartilhar com a família” (vem marcado). Desmarcado, é registro interno da equipe: a família não vê nem é avisada. Secretaria, administração e o estudante nunca veem. Escreva de forma objetiva e respeitosa.", (PROFESSOR, COORDENACAO, DIRECAO)),
    ("Por que o painel mostra “—” e não 0?",
     "“—” quer dizer que não há registro no período, por exemplo, uma chamada que não foi lançada. Zero seria uma afirmação falsa.",
     GESTAO + (PROFESSOR, SECRETARIA, ADMIN)),
    ("Funciona no celular?",
     "Sim. O menu vira uma gaveta (botão no canto superior esquerdo) e as tabelas viram listas.", TODOS),
]


def _url(name):
    try:
        return reverse(name)
    except NoReverseMatch:
        return None


# Glossário (Prompt 9 §8.11). Cada definição foi conferida no código que
# implementa a regra; mudou a regra, mude o texto. (termo, definição, perfis)
EQUIPE = (ADMIN, DIRECAO, COORDENACAO, SECRETARIA, PROFESSOR)
GLOSSARY = [
    ("Ano letivo e período",
     "O ano letivo vai do início ao fim cadastrados pela escola. Os períodos (bimestres, por exemplo) "
     "vêm do calendário oficial publicado e aparecem no seletor de período dos painéis.", TODOS),
    ("Avaliação publicada",
     "Avaliação cujas notas o professor liberou. Antes disso é rascunho: a família e o estudante não "
     "veem a nota, e ela não entra em nenhuma média ou indicador. A data da prova pode ser divulgada "
     "antes da nota.", TODOS),
    ("Média da disciplina",
     "Calculada só com avaliações publicadas, pela fórmula que a escola escolheu para a disciplina: "
     "média aritmética, ponderada (pelos pesos das avaliações), melhor nota ou soma. Sem regra "
     "cadastrada, vale a média aritmética com aprovação em 6.", TODOS),
    ("Frequência",
     "Percentual dos dias com chamada em que o estudante estava presente. Atraso conta como "
     "presença. A escola define o limite de faltas em Regras e limites (25% por padrão); a LDB "
     "exige frequência mínima de 75% (Lei 9.394/1996, art. 24, VI).", TODOS),
    ("Falta justificada",
     "Falta com justificativa aceita pela secretaria. A justificativa fica registrada, mas não apaga "
     "a falta da frequência oficial.", TODOS),
    ("Atividade de casa",
     "Tarefa publicada para a turma inteira: a mesma atividade vale para todos os estudantes "
     "matriculados. Quem entra na turma recebe as que ainda estão no prazo (ou não têm prazo); quem sai conserva as do "
     "período em que esteve lá.", TODOS),
    ("Situação da atividade",
     "Pendente: ainda no prazo. A vencer: o prazo termina em até 2 dias. Prazo encerrado: a data de "
     "entrega passou. Agendada: publicada com data futura, ainda não aparece à família. Cancelada: "
     "o professor cancelou; o registro fica no histórico.", TODOS),
    ("Entrega registrada e “Estou ciente”",
     "Quem registra se a tarefa foi entregue (no prazo, com atraso ou não entregue) é o professor. "
     "“Estou ciente” é só a confirmação de que a família ou o estudante leu a tarefa.", TODOS),
    ("Trabalho em grupo",
     "Um único trabalho da turma, dividido em grupos. Cada família vê o grupo do próprio filho, com o "
     "nome dos colegas daquele grupo, e nada além disso sobre eles.", TODOS),
    ("Taxa de entrega",
     "Entre as atividades com entrega registrada pelo professor, quantas foram entregues (no prazo ou "
     "com atraso). Atividade sem registro não conta como não entregue.", EQUIPE + (RESPONSAVEL,)),
    ("Cobertura de registro",
     "Quantas das atividades com prazo vencido tiveram a entrega registrada. Mede a qualidade do dado, "
     "não o estudante: com cobertura baixa, a taxa de entrega diz pouco.", EQUIPE),
    ("Grupo pequeno",
     "Nos painéis, grupos com menos de 5 estudantes não aparecem em comparações, para que ninguém "
     "seja identificado pelo resultado do grupo.", EQUIPE),
    ("Ocorrência",
     "Registro de um fato (um incidente ou um comportamento), com acompanhamento até ser concluído. A "
     "família do estudante vê; o próprio estudante, não.", EQUIPE + (RESPONSAVEL,)),
    ("Observação pedagógica",
     "Registro sobre a aprendizagem (dificuldades, avanços, estratégias). A equipe pedagógica e os "
     "responsáveis do estudante veem; secretaria, administração e o próprio estudante, não.",
     EQUIPE + (RESPONSAVEL,)),
    ("Plano de acompanhamento",
     "Objetivo combinado para um estudante, com estratégias, critério de sucesso, prazo e o registro "
     "da evolução. Plano ativo sem registro há mais de 30 dias ou com prazo vencido é sinalizado.",
     EQUIPE + (RESPONSAVEL,)),
    ("Busca ativa",
     "Acompanhamento de estudantes com faltas seguidas ou frequência baixa, com as ações da escola "
     "registradas e, quando preciso, a comunicação ao Conselho Tutelar (LDB, art. 12, VIII).", EQUIPE),
    ("Vínculo aprovado",
     "Ligação entre a conta do responsável e o estudante, conferida pela secretaria. Sem ela, nenhum "
     "dado do estudante aparece para o responsável.", (ADMIN, SECRETARIA, RESPONSAVEL)),
    ("Cenário simulado",
     "Conta do tipo “e se” feita no simulador do painel do estudante. Usa as regras reais de média e "
     "de frequência, mas não grava nada nem muda notas ou faltas.", TODOS),
]


def build(user, visible_urls):
    """Guias e perguntas deste perfil, com links só para telas que ele abre."""
    visible = set(visible_urls)
    guides = []
    for title, icon, roles, steps in GUIDES:
        if user.role not in roles:
            continue
        rendered = []
        for text, url_name in steps:
            url = _url(url_name) if url_name else None
            rendered.append({"text": text, "url": url if url in visible else None})
        guides.append({"title": title, "icon": icon, "steps": rendered})
    faq = [{"q": q, "a": a} for q, a, roles in FAQ if user.role in roles]
    glossary = sorted(({"term": t, "text": d} for t, d, roles in GLOSSARY if user.role in roles),
                      key=lambda g: g["term"].lower())
    return {"guides": guides, "faq": faq, "glossary": glossary}
