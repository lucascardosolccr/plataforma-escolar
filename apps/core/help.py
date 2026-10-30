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
]

# Perguntas comuns a todos os perfis: (pergunta, resposta, perfis)
FAQ = [
    ("Como encontro uma tela ou um estudante rapidamente?",
     "Aperte Ctrl+K (ou /) e digite. A busca mostra páginas, ações e, para a equipe, estudantes e turmas.", TODOS),
    ("Posso deixar uma página mais à mão?",
     "Sim. A estrela na barra superior guarda a página nos Favoritos, no topo do menu. Os favoritos ficam neste navegador.", TODOS),
    ("Como sei onde estou?",
     "A trilha no topo (Início / seção / página) mostra o caminho. Clique num nível para voltar a ele.", TODOS),
    ("Esqueci minha senha.",
     "Procure a secretaria da escola: ela gera uma senha temporária, que você troca no primeiro acesso.", TODOS),
    ("Quem vê os dados do meu filho?",
     "Só a equipe da escola, conforme a função, e os responsáveis com vínculo aprovado. As observações pedagógicas ficam com a equipe pedagógica e com vocês: a secretaria e a administração não as veem.",
     (RESPONSAVEL,)),
    ("Por que uma nota não aparece?",
     "O professor ainda não publicou a avaliação. Enquanto está em rascunho, só ele vê.", (RESPONSAVEL, ESTUDANTE)),
    ("A família vê o que eu escrevo na observação pedagógica?",
     "Sim: os responsáveis com vínculo aprovado veem as observações do próprio filho. Secretaria, administração e o estudante não veem. Escreva de forma objetiva e respeitosa.", (PROFESSOR, COORDENACAO, DIRECAO)),
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
    return {"guides": guides, "faq": faq}
