"""Navegação da plataforma: um único lugar define o que cada perfil vê.

A barra lateral, a busca global (Ctrl+K), a trilha de navegação e os atalhos
da tela inicial saem daqui. Antes, o menu era um template de 150 linhas com
``{% if %}`` por perfil, repetido em parte na home — e itens divergiam (o
estudante perdia "Meu painel" fora da tela inicial).

Mostrar um item NÃO é permissão: cada view continua conferindo o acesso no
servidor. O teste ``test_navigation`` garante o caminho inverso — todo item
mostrado a um perfil abre (HTTP 200) para esse perfil.
"""

from dataclasses import dataclass

from django.urls import NoReverseMatch, reverse

from .models import Role

ADMIN = Role.ADMIN.value
DIRECAO = Role.DIRECAO.value
COORDENACAO = Role.COORDENACAO.value
SECRETARIA = Role.SECRETARIA.value
PROFESSOR = Role.PROFESSOR.value
RESPONSAVEL = Role.RESPONSAVEL.value
ESTUDANTE = Role.ESTUDANTE.value


@dataclass(frozen=True)
class Item:
    label: str
    url_name: str
    icon: str
    # Prefixos de view_name que marcam o item como ativo (telas filhas).
    match: tuple = ()
    desc: str = ""


def _own_student_args(user):
    student = getattr(user, "student_record", None)
    return [student.pk] if student is not None else None


ITEMS = {
    "home": Item("Início", "home", "house", desc="Resumo do dia"),
    "pending": Item("Pendências", "pending_center", "list-checks", ("pending_center",),
                    "O que falta resolver, num lugar só"),
    "calendar": Item("Calendário", "school_calendar:calendar_index", "calendar-days",
                     ("school_calendar:",), "Prazos, avaliações e registros por data"),
    "menu": Item("Cardápio", "rotina:menu", "heart-handshake", ("rotina:menu",), "Lanche e refeições da semana"),
    "schedule": Item("Horários", "rotina:schedule_index", "clock", ("rotina:schedule",), "Quadro de aulas da turma"),
    # Família
    "children": Item("Meus filhos", "my_children", "users",
                     ("my_children", "student_detail", "analytics:student_dashboard"),
                     "Ficha de cada estudante vinculado"),
    "fam_activities": Item("Atividades de casa", "pedagogy:activity_list", "notebook-pen",
                           ("pedagogy:activity_",), "Tarefas das turmas dos seus filhos"),
    "fam_works": Item("Trabalhos em grupo", "pedagogy:group_work_list", "users-round",
                      ("pedagogy:group_work_",), "O grupo de cada filho"),
    "fam_grades": Item("Notas", "pedagogy:evaluation_list", "graduation-cap",
                       ("pedagogy:evaluation_",), "Avaliações publicadas"),
    "outlook": Item("Agenda e faltas", "pedagogy:outlook", "calendar-days", ("pedagogy:outlook",),
                    "O que vence logo e quantas faltas ainda cabem no ano"),
    "fam_attendance": Item("Frequência", "pedagogy:attendance_list", "calendar-check",
                           ("pedagogy:attendance_",), "Presenças, atrasos e faltas"),
    "justify": Item("Justificar falta", "pedagogy:justification_create", "file-check",
                    ("pedagogy:justification_create",), "Enviar à secretaria"),
    "links": Item("Vínculos", "link_list", "link", ("link_",), "Estudantes vinculados à conta"),
    "fam_applications": Item("Pré-cadastro", "family_applications", "id-card",
                             ("family_applications", "application_"), "Cadastrar um filho na escola"),
    "link_request": Item("Solicitar vínculo", "link_request", "user-check", (),
                         "Pedir acesso a um estudante"),
    # Estudante
    "my_dashboard": Item("Meu painel", "analytics:student_dashboard", "chart-line",
                         ("analytics:student_dashboard",), "Médias, evolução e frequência"),
    "my_activities": Item("Minhas atividades", "pedagogy:activity_list", "notebook-pen",
                          ("pedagogy:activity_",), "Tarefas da sua turma"),
    "my_works": Item("Trabalhos em grupo", "pedagogy:group_work_list", "users-round",
                     ("pedagogy:group_work_",), "Seu grupo e colegas"),
    "my_grades": Item("Minhas notas", "pedagogy:evaluation_list", "graduation-cap",
                      ("pedagogy:evaluation_",), "Avaliações publicadas"),
    "my_attendance": Item("Minha frequência", "pedagogy:attendance_list", "calendar-check",
                          ("pedagogy:attendance_",), "Presenças e faltas"),
    # Sala de aula / pedagógico
    "classrooms": Item("Minhas turmas", "my_classrooms", "school",
                       ("my_classrooms", "student_detail", "analytics:student_dashboard",
                        "analytics:class_dashboard"),
                       "Estudantes das suas atribuições"),
    "evaluations": Item("Avaliações e notas", "pedagogy:evaluation_list", "graduation-cap",
                        ("pedagogy:evaluation_",), "Criar, lançar e publicar"),
    "activities": Item("Atividades de casa", "pedagogy:activity_list", "notebook-pen",
                       ("pedagogy:activity_",), "Tarefas por turma e entregas"),
    "works": Item("Trabalhos em grupo", "pedagogy:group_work_list", "users-round",
                  ("pedagogy:group_work_",), "Grupos, integrantes e entregas"),
    "attendance": Item("Frequência", "pedagogy:attendance_list", "calendar-check",
                       ("pedagogy:attendance_",), "Registro diário por turma"),
    "occurrences": Item("Ocorrências", "pedagogy:occurrence_list", "flag",
                        ("pedagogy:occurrence_",), "Registros disciplinares"),
    "observations": Item("Observações", "pedagogy:observation_list", "eye",
                         ("pedagogy:observation_",), "Acompanhamento pedagógico"),
    "plans": Item("Planos de acompanhamento", "pedagogy:plan_list", "heart-handshake",
                  ("pedagogy:plan_",), "Intervenções individuais"),
    "justifications": Item("Justificativas", "pedagogy:justification_list", "file-check",
                           ("pedagogy:justification_",), "Faltas justificadas"),
    "active_search": Item("Busca ativa", "pedagogy:active_search", "user-check", ("pedagogy:active_search",),
                          "Muitas faltas: ações da escola e Conselho Tutelar"),
    # Cadastro e acadêmico
    "students": Item("Estudantes", "student_list", "id-card",
                     ("student_", "analytics:student_dashboard"), "Fichas e prontuários"),
    "guardians": Item("Responsáveis", "guardian_list", "users", ("guardian_",),
                      "Famílias cadastradas"),
    "applications": Item("Pré-cadastros", "application_review_list", "inbox",
                         ("application_review",), "Cadastros enviados pelas famílias"),
    "student_import": Item("Importar estudantes", "student_import", "file-text",
                           ("student_import", "student_photo_batch"), "Planilha Excel e fotos em lote"),
    "registration_cfg": Item("Cadastro pelas famílias", "registration_settings", "sliders-horizontal",
                             ("registration_settings",), "O que a família pode cadastrar"),
    "booking": Item("Reservas", "booking:agenda", "calendar-check", ("booking:",),
                    "Sala de informática, quadra, laboratório e equipamentos"),
    "care": Item("Saúde e retirada", "care:home", "user-check", ("care:",),
                 "Ficha de saúde, quem pode buscar e saídas antecipadas"),
    "school_library": Item("Biblioteca escolar", "library:catalog", "book-open", ("library:",),
                           "Livros da escola, empréstimos, devoluções e reservas"),
    "lost_found": Item("Achados e perdidos", "lostfound:list", "package", ("lostfound:",),
                       "Objetos encontrados na escola: reconheça e retire"),
    "gate_station": Item("Portaria", "gate:station", "id-card", ("gate:station", "gate:today", "gate:settings"),
                         "Entrada e saída com a carteirinha"),
    "gate_cards": Item("Carteirinhas", "gate:cards", "id-card", ("gate:cards", "gate:class_cards"),
                       "Emitir e imprimir por turma"),
    "gate_mine": Item("Carteirinha e entradas", "gate:mine", "id-card", ("gate:mine", "gate:card", "gate:history"),
                      "Carteirinha digital e horários de chegada"),
    "privacy_cfg": Item("Privacidade e encarregado", "privacy_edit", "shield", ("privacy",),
                        "Controlador e encarregado de dados (LGPD, art. 41)"),
    "staff_links": Item("Vínculos", "link_list", "link", ("link_",),
                        "Validar pedidos das famílias"),
    "enrollments": Item("Matrículas", "enrollment_list", "clipboard-list", ("enrollment_",),
                        "Estudante, turma e ano letivo"),
    "documents": Item("Declarações", "document_list", "file-text", ("document_",),
                      "Matrícula e frequência, com número e código"),
    "classes": Item("Turmas", "class_group_list", "layers", ("class_group_",),
                    "Organização por ano letivo"),
    "subjects": Item("Disciplinas", "subject_list", "book-open", ("subject_",),
                     "Componentes curriculares"),
    "years": Item("Anos letivos", "school_year_list", "calendar-days", ("school_year_",),
                  "Períodos letivos"),
    "official_calendar": Item("Calendário oficial", "school_calendar:official", "calendar-check",
                              ("school_calendar:official",), "Bimestres, férias, feriados e dias letivos"),
    "assignments": Item("Atribuições", "assignment_list", "user-cog", ("assignment_",),
                        "Professor, turma e disciplina"),
    "teacher_perms": Item("Permissões de professores", "teacher_permissions", "shield",
                          ("teacher_permission",), "Acesso extra a outras disciplinas"),
    "config": Item("Regras e limites", "pedagogy:config_edit", "sliders-horizontal",
                   ("pedagogy:config_", "pedagogy:academic_rule_"), "Médias e limite de faltas"),
    "users": Item("Usuários", "user_list", "shield", ("user_",), "Contas e auditoria"),
    "schools": Item("Escolas", "school_list", "building-2", ("school_list", "school_create", "school_edit"),
                    "Cadastrar escolas e gerar o convite da direção"),
    "team_invites": Item("Equipe e convites", "my_team", "user-check", ("school_team", "my_team"),
                         "Códigos para a equipe se cadastrar e aprovação de contas"),
    "error_log": Item("Falhas técnicas", "error_log", "triangle-alert", ("error_log",),
                      "Erros do servidor registrados"),
    "photos": Item("Fotografias", "photo_pending", "user-round", ("photo_",),
                   "Quem ainda não tem foto de identificação"),
    # Comunicação
    "notifications": Item("Notificações", "communication:notification_list", "bell",
                          ("communication:notification_",), "Avisos da plataforma"),
    "threads_staff": Item("Mensagens com famílias", "communication:thread_list", "message-circle",
                          ("communication:thread_",), "Conversas por estudante"),
    "threads_family": Item("Mensagens com a escola", "communication:thread_list", "message-circle",
                           ("communication:thread_",), "Professores e setores"),
    "announcements": Item("Comunicados", "communication:announcement_list", "megaphone",
                          ("communication:announcement_",), "Avisos da escola e das turmas"),
    "requests": Item("Solicitações", "communication:request_list", "inbox",
                     ("communication:request_",), "Pedidos de atendimento"),
    "authorizations": Item("Autorizações", "communication:authorization_list", "file-check",
                           ("communication:authorization_",), "Passeios e atividades com autorização da família"),
    "polls": Item("Consultas às famílias", "communication:poll_list", "list-checks", ("communication:poll_",),
                  "Uma pergunta, um voto por família"),
    # Análises
    "institutional": Item("Painel institucional", "analytics:institutional_dashboard",
                          "layout-dashboard", ("analytics:institutional_dashboard", "analytics:class_dashboard"),
                          "Indicadores da escola"),
    "secretaria_panel": Item("Painel da secretaria", "analytics:secretaria_panel",
                             "layout-dashboard", ("analytics:secretaria_panel",),
                             "Vínculos, matrículas e pendências"),
    "reports": Item("Relatórios", "analytics:report_hub", "file-text",
                    ("analytics:report_",), "Exportar CSV e imprimir"),
    "teacher_bi": Item("Meu painel de turmas", "analytics:teacher_dashboard", "chart-column",
                       ("analytics:teacher_dashboard",), "Médias, entregas e pendências"),
    "subject_bi": Item("Painéis por disciplina", "analytics:subject_index", "book-marked",
                       ("analytics:subject_",), "Resultados de cada disciplina"),
    "goals": Item("Metas da escola", "analytics:goals", "flag", ("analytics:goals", "analytics:goal_create",
                  "analytics:goal_edit"), "Indicadores com valor-alvo e prazo"),
    "quality": Item("Qualidade dos dados", "analytics:data_quality", "check",
                    ("analytics:data_quality",), "Lançamentos pendentes e inconsistências"),
    "methodology": Item("Metodologia dos indicadores", "analytics:methodology", "info",
                        ("analytics:methodology",), "Como cada número é calculado"),
    "help": Item("Ajuda", "help", "circle-help", ("help",), "Guias passo a passo e perguntas frequentes"),
    "notif_rules": Item("Avisos automáticos", "communication:notification_rules", "bell",
                        ("communication:notification_rules",), "Quais eventos avisam a família"),
    "prints_mine": Item("Atividades e impressões", "printing:mine", "printer",
                        ("printing:mine", "printing:create", "printing:edit", "printing:detail"),
                        "Pedir e acompanhar impressões"),
    "prints_queue": Item("Fila de impressão", "printing:queue", "printer",
                         ("printing:queue", "printing:detail"), "Analisar, imprimir e entregar"),
    "lesson_plans": Item("Planejamento", "pedagogy:lessonplan_list", "clipboard-check",
                         ("pedagogy:lessonplan_",), "Planos de aula e devolutivas da coordenação"),
    "diary": Item("Diário de classe", "pedagogy:diary_list", "notebook-pen", ("pedagogy:diary_",),
                  "O que foi trabalhado em cada aula"),
    "fam_diary": Item("Conteúdo das aulas", "pedagogy:diary_list", "notebook-pen", ("pedagogy:diary_",),
                      "O que foi trabalhado em cada aula"),
    "coord_panel": Item("Painel da coordenação", "coordination:panel", "layout-dashboard",
                        ("coordination:panel",), "Turmas, alertas e intervenções que você acompanha"),
    "coord_records": Item("Registros da coordenação", "coordination:records", "notebook-pen",
                          ("coordination:records",), "Orientações, reuniões e acompanhamentos"),
    "coord_designations": Item("Designação da coordenação", "coordination:designations", "user-cog",
                               ("coordination:designation",), "Quem acompanha quais turmas"),
    "curriculum": Item("Currículo", "curriculum:catalog", "book-marked",
                       ("curriculum:catalog", "curriculum:item_", "curriculum:coverage", "curriculum:evidence_"),
                       "BNCC, Currículo em Movimento e acompanhamento curricular"),
    "support": Item("Apoio à inclusão", "inclusion:overview", "heart-handshake", ("inclusion:",),
                    "Necessidades específicas, documentos e planos individualizados"),
    "support_guidance": Item("Orientações de apoio", "inclusion:guidance", "heart-handshake",
                             ("inclusion:guidance",), "Recursos e estratégias para estudantes das suas turmas"),
    "fam_support": Item("Necessidades e laudos", "inclusion:overview", "heart-handshake", ("inclusion:",),
                        "Informar a escola e acompanhar a análise"),
    "cognitio": Item("EIA-Cognitio", "cognitio:home", "chart-line", ("cognitio:",),
                     "Mapa de competências, alertas e intervenções por habilidade"),
    "norms": Item("Referências normativas", "curriculum:references", "book-open", ("curriculum:references",),
                  "LDB, BNCC, educação inclusiva e LGPD"),
    "exam_prep": Item("Conteúdos da prova", "study:list", "book-open", ("study:",),
                      "O que vai cair em cada prova e o que estudar"),
    "rubrics": Item("Rubricas", "pedagogy:rubric_list", "list-checks", ("pedagogy:rubric_",),
                    "Critérios e níveis para corrigir atividades"),
    "library": Item("Biblioteca de materiais", "study:library", "book-marked", ("study:library",),
                    "Materiais que os colegas compartilharam"),
    "fam_exam_prep": Item("Conteúdos da prova", "study:list", "book-open", ("study:",),
                          "O que vai cair nas provas e o que estudar"),
    "my_exam_prep": Item("Minhas provas", "study:list", "book-open", ("study:",),
                         "O que vai cair e por onde começar a estudar"),
    "meetings": Item("Reuniões", "meetings:list", "users-round", ("meetings:",),
                     "Reuniões e atendimentos: pauta, registro e encaminhamentos"),
}

# Itens do rodapé do menu, iguais para todos os perfis.
FOOTER = ["help"]

# Ações rápidas: aparecem na busca global e no topo da tela inicial.
ACTIONS = {
    "new_activity": Item("Nova atividade de casa", "pedagogy:activity_create", "plus"),
    "new_evaluation": Item("Nova avaliação", "pedagogy:evaluation_create", "plus"),
    "new_work": Item("Novo trabalho em grupo", "pedagogy:group_work_create", "plus"),
    "new_occurrence": Item("Registrar ocorrência", "pedagogy:occurrence_create", "plus"),
    "new_observation": Item("Registrar observação", "pedagogy:observation_create", "plus"),
    "new_plan": Item("Novo plano de acompanhamento", "pedagogy:plan_create", "plus"),
    "new_student": Item("Cadastrar estudante", "student_create", "plus"),
    "new_enrollment": Item("Nova matrícula", "enrollment_create", "plus"),
    "new_user": Item("Criar conta profissional", "user_create", "plus"),
    "new_thread": Item("Nova mensagem", "communication:thread_create", "message-circle"),
    "new_request": Item("Nova solicitação", "communication:request_create", "inbox"),
    "new_meeting": Item("Marcar reunião", "meetings:create", "plus"),
    "justify": ITEMS["justify"],
    "link_request": ITEMS["link_request"],
}

COMMUNICATION_STAFF = ("Comunicação", ["threads_staff", "announcements", "authorizations", "polls", "requests",
                                       "meetings", "notifications"])
# A administração cuida das contas e da configuração, não participa de reuniões.
COMMUNICATION_ADMIN = ("Comunicação", ["threads_staff", "announcements", "authorizations", "polls", "requests",
                                       "notifications"])

LAYOUT = {
    RESPONSAVEL: [
        (None, ["home", "pending", "calendar", "schedule", "menu"]),
        ("Acompanhamento", ["children", "outlook", "fam_diary", "fam_activities", "fam_works", "fam_exam_prep",
                            "fam_grades", "fam_attendance", "gate_mine", "care", "school_library"]),
        ("Escola", ["threads_family", "announcements", "authorizations", "polls", "requests", "meetings",
                    "lost_found", "notifications"]),
        ("Secretaria", ["fam_applications", "justify", "links", "fam_support"]),
        ("Análises", ["reports", "methodology"]),
    ],
    ESTUDANTE: [
        (None, ["home", "calendar", "schedule", "menu", "my_dashboard"]),
        ("Meus estudos", ["outlook", "fam_diary", "my_activities", "my_works", "my_exam_prep", "my_grades",
                         "my_attendance", "gate_mine", "school_library"]),
        # Comunicados da escola e da turma (a regra de acesso já os mostrava ao
        # estudante, mas o menu não tinha o caminho).
        ("Escola", ["announcements", "lost_found", "notifications"]),
    ],
    PROFESSOR: [
        (None, ["home", "pending", "calendar", "schedule", "menu"]),
        ("Sala de aula", ["classrooms", "lesson_plans", "diary", "curriculum", "cognitio", "attendance", "evaluations",
                          "exam_prep", "library", "activities", "rubrics", "prints_mine", "works", "booking",
                          "school_library"]),
        ("Acompanhamento", ["occurrences", "observations", "support_guidance", "justifications", "care",
                            "lost_found"]),
        COMMUNICATION_STAFF,
        ("Análises", ["teacher_bi", "subject_bi", "reports", "methodology", "norms"]),
    ],
    SECRETARIA: [
        (None, ["home", "pending", "calendar", "schedule", "menu"]),
        ("Secretaria", ["students", "applications", "student_import", "photos", "guardians", "staff_links",
                        "enrollments", "documents", "gate_cards", "gate_station", "care", "justifications",
                        "active_search", "support", "school_library", "lost_found"]),
        ("Acadêmico", ["classes", "subjects", "years", "official_calendar", "assignments", "teacher_perms"]),
        ("Pedagógico", ["evaluations", "activities", "prints_queue", "works", "attendance", "occurrences", "booking"]),
        COMMUNICATION_STAFF,
        ("Análises", ["secretaria_panel", "subject_bi", "quality", "reports", "methodology", "norms"]),
        ("Configuração", ["config", "registration_cfg"]),
    ],
    COORDENACAO: [
        (None, ["home", "pending", "calendar", "schedule", "menu"]),
        ("Coordenação", ["coord_panel", "lesson_plans", "diary", "curriculum", "cognitio", "prints_queue",
                         "coord_records", "gate_station", "care", "booking", "school_library", "lost_found"]),
        ("Pedagógico", ["students", "evaluations", "exam_prep", "library", "activities", "works", "attendance",
                        "occurrences", "observations", "plans", "support", "justifications",
                        "active_search"]),
        ("Acadêmico", ["classes", "subjects", "years", "assignments"]),
        COMMUNICATION_STAFF,
        ("Análises", ["institutional", "goals", "subject_bi", "quality", "reports", "methodology", "norms"]),
    ],
    DIRECAO: [
        (None, ["home", "pending", "calendar", "schedule", "menu"]),
        ("Coordenação", ["coord_panel", "lesson_plans", "diary", "curriculum", "cognitio", "prints_queue",
                         "coord_designations", "gate_station", "gate_cards", "care", "booking", "school_library",
                         "lost_found"]),
        ("Análises", ["institutional", "goals", "subject_bi", "quality", "reports", "methodology", "norms"]),
        ("Pedagógico", ["students", "evaluations", "exam_prep", "library", "activities", "works", "attendance",
                        "occurrences", "observations", "plans", "support", "justifications",
                        "active_search"]),
        ("Acadêmico", ["classes", "subjects", "years", "official_calendar", "teacher_perms"]),
        COMMUNICATION_STAFF,
        ("Configuração", ["team_invites", "registration_cfg", "privacy_cfg", "photos", "notif_rules"]),
    ],
    ADMIN: [
        (None, ["home", "pending", "calendar", "schedule", "menu"]),
        ("Administração", ["schools", "team_invites", "users", "coord_designations", "config", "registration_cfg",
                           "privacy_cfg", "notif_rules", "error_log", "booking"]),
        ("Cadastro", ["students", "applications", "student_import", "photos", "guardians", "staff_links",
                      "enrollments", "documents", "gate_cards", "gate_station", "care", "school_library",
                      "lost_found"]),
        ("Acadêmico", ["classes", "subjects", "years", "official_calendar", "assignments", "teacher_perms"]),
        ("Pedagógico", ["evaluations", "activities", "prints_queue", "works", "attendance", "occurrences",
                        "justifications"]),
        COMMUNICATION_ADMIN,
        ("Análises", ["institutional", "goals", "secretaria_panel", "subject_bi", "quality", "reports", "methodology",
                      "norms"]),
    ],
}

ROLE_ACTIONS = {
    RESPONSAVEL: ["new_thread", "justify", "new_request", "link_request"],
    ESTUDANTE: [],
    PROFESSOR: ["new_activity", "new_evaluation", "new_work", "new_occurrence",
                "new_observation", "new_thread", "new_meeting"],
    SECRETARIA: ["new_student", "new_enrollment", "new_thread", "new_meeting"],
    COORDENACAO: ["new_plan", "new_observation", "new_occurrence", "new_thread", "new_meeting"],
    DIRECAO: ["new_occurrence", "new_thread", "new_meeting"],
    ADMIN: ["new_user", "new_student", "new_enrollment"],
}


def _resolve(item, user):
    args = None
    if item.url_name == "analytics:student_dashboard":
        args = _own_student_args(user)
        if args is None:
            return None
    try:
        return reverse(item.url_name, args=args)
    except NoReverseMatch:  # rota removida: some do menu em vez de quebrar a página
        return None


def _is_active(item, view_name):
    return _match_len(item, view_name) > 0


def _match_len(item, view_name):
    """Quão específico é o casamento do item com a tela atual (0 = não casa).
    O mais específico vence: "student_import" ganha de "student_"."""
    if not view_name:
        return 0
    if view_name == item.url_name:
        return 10_000
    return max((len(p) for p in item.match if view_name.startswith(p)), default=0)


def _family_registration_on(user):
    from apps.registry.models import RegistrationSettings

    cfg = RegistrationSettings.objects.filter(school_id=user.school_id).first()
    return bool(cfg and cfg.family_mode == RegistrationSettings.MODE_FULL)


def _institutional(user):
    """Coordenação restrita a algumas turmas usa o painel da coordenação, não a visão da escola toda."""
    from apps.analytics.access import can_view_institutional_dashboard

    return can_view_institutional_dashboard(user)


# Itens que só aparecem quando a escola liga a função ou o perfil alcança a tela (a view também confere).
def _platform_admin(user):
    from .invites import is_platform_admin

    return is_platform_admin(user)


def _has_school(user):
    from .invites import is_platform_admin

    return user.school_id is not None or is_platform_admin(user)


CONDITIONS = {"fam_applications": _family_registration_on, "institutional": _institutional, "goals": _institutional,
              "schools": _platform_admin, "team_invites": _has_school}


def build(user, view_name=None):
    """Seções, ações e trilha de navegação do usuário para esta requisição."""
    sections, flat = [], []
    active, best = None, 0
    for title, keys in LAYOUT.get(user.role, [(None, ["home", "calendar"])]):
        items = []
        for key in keys:
            item = ITEMS[key]
            if key in CONDITIONS and not CONDITIONS[key](user):
                continue
            url = _resolve(item, user)
            if url is None:
                continue
            entry = {
                "key": key, "label": item.label, "url": url, "icon": item.icon,
                "desc": item.desc, "section": title or "", "active": False,
            }
            # O item mais específico vence: "Início" só é ativo na própria home.
            score = _match_len(item, view_name)
            if score and (active is None or score > best):
                if active is not None:
                    active["active"] = False
                entry["active"] = True
                active, best = entry, score
            items.append(entry)
            flat.append(entry)
        if items:
            sections.append({"title": title, "items": items})

    footer = []
    for key in FOOTER:
        item = ITEMS[key]
        entry = {"key": key, "label": item.label, "url": _resolve(item, user), "icon": item.icon,
                 "desc": item.desc, "section": "", "active": False}
        if active is None and _is_active(item, view_name):
            entry["active"] = True
            active = entry
        footer.append(entry)
        flat.append(entry)

    actions = []
    for key in ROLE_ACTIONS.get(user.role, []):
        item = ACTIONS[key]
        url = _resolve(item, user)
        if url is not None:
            actions.append({"key": key, "label": item.label, "url": url, "icon": item.icon})

    crumbs = []
    if active is not None and active["key"] != "home":
        if active["section"]:
            crumbs.append({"label": active["section"], "url": None})
        crumbs.append({
            "label": active["label"],
            "url": None if view_name == ITEMS[active["key"]].url_name else active["url"],
        })
    # Dados da busca global: só o que este perfil já vê no menu.
    palette = [
        {"label": i["label"], "url": i["url"], "icon": i["icon"],
         "group": "Ir para", "hint": i["section"] or i["desc"], "key": i["key"]}
        for i in flat
    ] + [
        {"label": a["label"], "url": a["url"], "icon": a["icon"], "group": "Ações",
         "hint": "", "key": a["key"]}
        for a in actions
    ]
    return {"sections": sections, "footer": footer, "flat": flat, "actions": actions, "crumbs": crumbs,
            "active": active, "palette": palette}


def all_visible_urls(user):
    """Todas as URLs que o menu e as ações mostram a este usuário (para testes)."""
    nav = build(user)
    return [i["url"] for i in nav["flat"]] + [a["url"] for a in nav["actions"]]
