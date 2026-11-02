"""Matriz mestra de requisitos dos nove prompts (Prompt 11), com evidência conferida.

Uso:
    python tools/matriz_requisitos.py            # confere e grava ../docs/MATRIZ_MESTRA_DE_REQUISITOS.md
    python tools/matriz_requisitos.py --check    # só confere (o teste test_requirements_matrix usa isto)

Por que um script: a matriz anterior citava testes que não existiam
("test_guardian_link_approval", "test_academic_rule_calculation"...) e um CSS
apagado havia semanas. Aqui cada evidência é conferida: um caminho precisa
existir e um ``arquivo::test_nome`` precisa ter ``def test_nome`` naquele
arquivo. Item "VALIDADO" precisa de pelo menos um teste automatizado.

Situações:
    VALIDADO          implementado e coberto por teste automatizado que passa na suíte
    VERIFICADO        implementado e conferido no navegador ou por inspeção, sem teste automatizado
    PARCIAL           existe, mas não cobre tudo o que o prompt pede (a pendência diz o quê)
    DECISÃO           não implementado de propósito, com a razão registrada
    NÃO IMPLEMENTADO  falta, sem impedimento técnico
    BLOQUEADO         depende de algo fora do ambiente (a pendência diz o quê)
"""

import importlib.util
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # plataforma-escolar/
DOCS = ROOT.parent / "docs"
OUT = DOCS / "MATRIZ_MESTRA_DE_REQUISITOS.md"

STATES = ("VALIDADO", "VERIFICADO", "PARCIAL", "DECISÃO", "NÃO IMPLEMENTADO", "BLOQUEADO")

PROMPTS = {
    "P2": "Prompt 2 - Correções e testes.md",
    "P3": "Prompt 3 - Design.md",
    "P4": "Prompt 4 - Entender e melhorar aplicação.md (idêntico ao Prompt 10)",
    "P5": "Prompt 5 - Corrigir erros e implementar atividade em grupo.md",
    "P6": "Prompt 6 - Redesign e Análise de dados.md",
    "P7": "Prompt 7 - Redesign e Análise de dados.md",
    "P8": "Prompt 8 - Redesign.md",
    "P9": "Prompt 9 - Novas funções.md",
    "P18": "PROMPT 18 - Evolução de diagnóstico e recomendações.md",
}


@dataclass
class R:
    id: str
    origem: str          # "P9 §5.3; P6 §6.7"
    requisito: str
    criterio: str        # critério objetivo de aceitação
    evidencia: list      # caminhos ou "caminho::test_nome" (relativos a plataforma-escolar/)
    situacao: str
    pendencia: str = ""
    prioridade: str = "P1"
    rodada: str = ""
    extra: dict = field(default_factory=dict)


T = "apps/{}/tests/{}.py::{}".format  # atalho: T("pedagogy", "test_pedagogy", "test_x")

REQS = [
    # ================================================================== P2
    R("P2-01", "P2 §2; P3 §13; P5 §11; P6 §12; P7 §15; P8 §9; P9 §18",
      "Custo zero absoluto: nenhuma dependência paga, cota gratuita ou serviço externo obrigatório",
      "requirements.txt só com bibliotecas livres; nenhuma origem externa nas páginas; CSP só 'self'",
      ["requirements.txt", T("core", "test_no_external_assets", "test_templates_reference_no_external_host"),
       T("core", "test_redesign_round2", "test_csp_forbids_inline_script")], "VALIDADO", prioridade="P0", rodada="R1"),
    R("P2-02", "P2 §4.1", "Botões e links sem ação ou que levam a erro",
      "Todo item de menu de cada perfil abre (200); nenhum link mostrado leva a 403/500",
      [T("core", "test_navigation", "test_every_menu_item_and_action_opens_for_each_role"),
       T("core", "test_link_integrity", "test_no_shown_link_leads_to_forbidden_or_error")], "VALIDADO", rodada="R1"),
    R("P2-03", "P2 §4.1; P5 §4.1", "Formulários que não salvam campos (campo do ModelForm ausente do template é apagado)",
      "Todo campo de formulário aparece no HTML renderizado",
      ["apps/core/tests/test_navigation.py"], "VALIDADO", rodada="R1",
      extra={"nota": "EveryFormFieldIsRenderedTests em test_navigation.py"}),
    R("P2-04", "P2 §4.1", "Parâmetros malformados na URL não derrubam a página",
      "?estudante=abc, data inválida e página inválida são tratados como filtro ausente",
      ["apps/pedagogy/tests/test_malformed_params.py",
       T("pedagogy", "test_pedagogy", "test_malformed_date_filter_is_ignored"),
       T("pedagogy", "test_pedagogy", "test_invalid_page_falls_back_instead_of_breaking")], "VALIDADO", rodada="R1"),
    R("P2-05", "P2 §4.3", "Isolamento de dados entre escolas",
      "Usuário de outra escola não lista, abre nem exporta registros",
      [T("registry", "test_registry", "test_list_isolated_between_schools"),
       T("core", "test_rbac", "test_detail_is_isolated_between_schools"),
       T("analytics", "test_analytics", "test_cross_school_is_denied")], "VALIDADO", prioridade="P0", rodada="R1"),
    R("P2-06", "P2 §4.3; P5 §4.4", "Unicidade e duplicidades indevidas no banco",
      "Turma, disciplina, ano, matrícula ativa e vínculo duplicados são recusados",
      [T("academics", "test_academics", "test_duplicate_turma_rejected"),
       T("registry", "test_registry", "test_duplicate_active_enrollment_blocked"),
       T("registry", "test_remediation", "test_duplicate_guardian_link_is_rejected")], "VALIDADO", rodada="R2"),
    R("P2-07", "P2 §4.3; P2 §8.5", "Backup e restauração verificados",
      "Backup íntegro; ciclo backup → perda → restauração recupera o registro; restauração guarda cópia do banco anterior",
      ["apps/core/backup.py", T("core", "test_backup", "test_full_cycle_recovers_deleted_record"),
       T("core", "test_backup", "test_restore_refuses_corrupt_backup_without_touching_database")], "VALIDADO", prioridade="P0", rodada="R2"),
    R("P2-08", "P2 §4.5; P5 §4.2", "Desempenho: consultas que não crescem com o volume (N+1)",
      "Listas e painéis com número de consultas constante",
      [T("pedagogy", "test_pedagogy", "test_family_list_query_count_is_flat"),
       T("analytics", "test_dashboard_queries", "test_class_dashboard_does_not_grow_with_students"),
       T("analytics", "test_bi", "test_query_budget_does_not_grow_with_students")], "VALIDADO", prioridade="P2", rodada="R13"),
    R("P2-09", "P2 §4.5", "Paginação em listas extensas", "Listas paginadas sem perder registros entre páginas",
      [T("pedagogy", "test_pedagogy", "test_nothing_is_lost_across_pages"),
       T("pedagogy", "test_pedagogy", "test_pager_keeps_active_filters")], "VALIDADO", prioridade="P2"),
    R("P2-10", "P2 §5.1", "Cadastro de pais e responsáveis (cadastro público só cria responsável)",
      "Cadastro público cria só perfil responsável, mesmo com POST forjado",
      [T("core", "test_signup", "test_signup_creates_responsavel_only"),
       T("core", "test_signup", "test_signup_cannot_elevate_role_even_with_crafted_post")], "VALIDADO"),
    R("P2-11", "P2 §5.2", "Cadastro e perfil individual do estudante",
      "Secretaria cria e edita; professor e responsável não; ficha isolada por escola",
      [T("registry", "test_registry", "test_create_student_updates_lists"),
       T("registry", "test_registry", "test_professor_cannot_create_student")], "VALIDADO"),
    R("P2-12", "P2 §5.3", "Associação segura responsável–estudante, com aprovação",
      "Pedido por nome; só a secretaria aprova; antes da aprovação nada aparece",
      [T("registry", "test_registry", "test_responsavel_cannot_view_student_before_approval"),
       T("registry", "test_registry", "test_secretaria_approve_grants_access"),
       T("registry", "test_registry", "test_other_family_cannot_view_student")], "VALIDADO", prioridade="P0"),
    R("P2-13", "P2 §5.4", "Turmas, séries, disciplinas e matrículas; rematrícula",
      "Matrícula única ativa por ano; rematrícula em lote preserva histórico",
      [T("registry", "test_registry", "test_enrollment_and_professor_visibility"),
       T("registry", "test_rollover", "test_moves_selected_and_keeps_history")], "VALIDADO"),
    R("P2-14", "P2 §5.7", "Registro e publicação de notas, com auditoria e rascunho",
      "Só o professor atribuído lança; família só vê publicada; publicada não é editada",
      [T("pedagogy", "test_pedagogy", "test_grade_batch_and_audit"),
       T("pedagogy", "test_pedagogy", "test_responsavel_does_not_see_draft"),
       T("pedagogy", "test_pedagogy", "test_published_evaluation_cannot_be_edited_or_deleted")], "VALIDADO"),
    R("P2-15", "P2 §5.9", "Frequência, faltas e atrasos",
      "Chamada em lote, única por dia; responsável vê só o filho",
      [T("pedagogy", "test_pedagogy", "test_batch_register_and_unique_per_day"),
       T("pedagogy", "test_pedagogy", "test_responsavel_sees_only_child_in_class_grid")], "VALIDADO"),
    R("P2-16", "P2 §5.10", "Justificativas e atestados (não apagam a falta oficial)",
      "Secretaria aprova sem alterar a frequência; solicitante é avisado",
      [T("pedagogy", "test_pedagogy", "test_secretaria_approves_without_changing_official_attendance"),
       T("communication", "test_communication", "test_justification_resolution_notifies_requester")], "VALIDADO"),
    R("P2-17", "P2 §5.12", "Advertências e ocorrências com acompanhamento",
      "Professor só registra para aluno próprio; família vê; estudante não",
      [T("pedagogy", "test_pedagogy", "test_professor_cannot_occurrence_student_outside_class"),
       T("registry", "test_student_account", "test_cannot_list_occurrences")], "VALIDADO"),
    R("P2-18", "P2 §5.14; P9 §6.4", "Pendências documentais e cadastros incompletos",
      "Painel da secretaria e central de pendências mostram o que falta",
      ["apps/core/views_photo.py", T("core", "test_pending", "test_family_unjustified_absences_and_justification_covers"),
       T("analytics", "test_analytics", "test_secretaria_panel_restricted")], "VALIDADO", prioridade="P2"),
    R("P2-19", "P2 §5.15", "Comunicação entre perfis (mensagens, comunicados, solicitações)",
      "Responsável não escreve a responsável; não participante não abre conversa; outra escola não vê",
      [T("communication", "test_communication", "test_thread_creation_blocks_responsavel_to_responsavel"),
       T("communication", "test_communication", "test_non_participant_cannot_view_thread"),
       T("communication", "test_communication", "test_secretaria_resolves_and_notifies_requester")], "VALIDADO"),
    R("P2-20", "P2 §5.16; P9 §8.5", "Central de notificações (só interna)",
      "Eventos reais geram aviso; marcar lida não afeta outra pessoa",
      [T("communication", "test_communication", "test_activity_publication_notifies_guardian"),
       T("core", "test_redesign_round2", "test_mark_selected_read_never_touches_someone_else")], "VALIDADO"),
    R("P2-21", "P2 §5.17; P2 §7", "Upload de fotografias e documentos protegido",
      "Mídia nunca por URL pública; tipo e conteúdo conferidos; foto sem EXIF",
      [T("core", "test_static", "test_media_never_public"),
       T("registry", "test_registry", "test_invalid_image_content_rejected"),
       T("inclusion", "test_inclusion", "test_image_is_reencoded_without_exif")], "VALIDADO", prioridade="P0"),
    R("P2-22", "P2 §5.18; P9 §5", "Dashboard individual de evolução acadêmica",
      "Painel do estudante com notas, frequência, atividades e trajetória, respeitando o acesso",
      [T("analytics", "test_bi_access", "test_student_panel_and_exports"),
       T("analytics", "test_analytics", "test_guardian_sees_own_child_only")], "VALIDADO"),
    R("P2-23", "P2 §5.21; P6 §6.5", "Identificação de dificuldades de aprendizagem (sinais, sem rótulo)",
      "Observações pedagógicas e habilidades consolidadas, ocultas à secretaria e à administração",
      [T("analytics", "test_analytics", "test_observations_hidden_from_admin"),
       T("core", "test_navigation", "test_secretaria_and_admin_do_not_see_pedagogical_observations")], "VALIDADO"),
    R("P2-24", "P2 §5.22; P9 §8.4", "Planos de intervenção pedagógica com histórico",
      "Plano com evoluções; comparação antes/depois no painel",
      [T("analytics", "test_bi", "test_intervention_before_after"),
       T("pedagogy", "test_plan_followup", "test_coordination_edits_plan_but_not_the_student")], "VALIDADO"),
    R("P2-25", "P2 §5.23; P6 §6.10; P9 §8.8", "Relatórios e exportações respeitando permissão e filtro",
      "CSV/Excel com contexto, auditados, no escopo do perfil; fórmula neutralizada",
      [T("analytics", "test_analytics", "test_csv_respects_role_scope"),
       T("analytics", "test_bi_access", "test_export_is_audited"),
       T("analytics", "test_bi_access", "test_xlsx_is_valid_and_neutralizes_formulas")], "VALIDADO", prioridade="P0"),
    R("P2-26", "P2 §5.24; P3 §9", "Busca, filtros, tabelas ordenáveis e calendário",
      "Ordenação no servidor mantém filtros; busca global restrita ao escopo",
      [T("core", "test_redesign_round2", "test_sort_header_keeps_filters_and_announces_order"),
       T("core", "test_global_search", "test_staff_sees_own_school_only")], "VALIDADO", prioridade="P2"),
    R("P2-27", "P2 §5.25; P2 §7", "Autenticação e recuperação de conta",
      "Login auditado; redefinição de senha pela escola com senha temporária forte e troca obrigatória",
      [T("core", "test_auth", "test_login_failure_redirects_and_logs_audit"),
       T("core", "test_password_reset", "test_generated_password_is_long_and_unambiguous")], "PARCIAL",
      pendencia="Recuperação por e-mail sem a escola não existe: depende de servidor de e-mail (custo ou cota). "
                "A redefinição é feita pela secretaria/administração.", prioridade="P2"),
    R("P2-28", "P2 §7", "Proteção contra tentativas abusivas de login",
      "Cinco falhas bloqueiam o usuário; muitas falhas de um endereço bloqueiam o endereço; não revela se a conta existe",
      [T("core", "test_redesign_round2", "test_five_failures_lock_the_username_even_with_right_password"),
       T("core", "test_redesign_round2", "test_lock_does_not_reveal_if_account_exists")], "VALIDADO", prioridade="P0"),
    R("P2-29", "P2 §7", "Sessão curta em computador compartilhado",
      "Sessão termina ao fechar o navegador e após 8 h sem uso",
      [T("core", "test_redesign_round2", "test_session_is_short_and_ends_with_the_browser")], "VALIDADO", prioridade="P0"),
    R("P2-30", "P2 §7", "Autorização horizontal e vertical no servidor",
      "Ninguém eleva o próprio perfil; família não abre outro estudante pela URL",
      [T("core", "test_rbac", "test_user_cannot_elevate_own_role"),
       T("registry", "test_student_account", "test_cannot_open_another_students_dashboard")], "VALIDADO", prioridade="P0"),
    R("P2-31", "P2 §6", "Registro de falhas técnicas e monitoramento",
      "Erros 500 e alertas de segurança gravados em arquivo rotativo e visíveis ao administrador",
      ["config/settings.py", T("core", "test_error_log", "test_server_errors_are_configured_to_be_recorded"),
       T("core", "test_error_log", "test_only_admin_sees_the_page")], "VALIDADO", prioridade="P2", rodada="R2",
      extra={"nota": "Implementado em 02/11/2026: antes não havia LOGGING e o erro 500 se perdia."}),
    R("P2-32", "P2 §6", "Importação validada de dados escolares",
      "Importação de estudantes com validação e sem duplicar",
      ["apps/registry/importer.py", "apps/registry/tests/test_import.py"], "VALIDADO", prioridade="P2"),
    R("P2-33", "P2 §6", "Indicadores de qualidade e integridade dos dados",
      "Painel de qualidade detecta notas faltando e chamada parcial; só gestão vê",
      [T("analytics", "test_bi", "test_quality_detects_missing_grades_and_partial_attendance"),
       T("analytics", "test_bi_access", "test_data_quality_only_management")], "VALIDADO", prioridade="P2"),
    R("P2-34", "P2 §6", "Confirmação de leitura de comunicados",
      "Leitura de comunicado registrada por pessoa",
      [T("communication", "test_communication", "test_guardian_sees_only_children_announcements")], "VALIDADO", prioridade="P3"),
    R("P2-35", "P2 §6; P9 §8.9", "Registro de reuniões e encaminhamentos",
      "Reunião com pauta, participantes, registro, encaminhamentos com responsável e prazo",
      ["apps/meetings/models.py", T("meetings", "test_meetings", "test_follow_up_responsible_is_notified_and_concludes"),
       T("meetings", "test_meetings", "test_family_sees_summary_but_never_staff_notes")], "VALIDADO", prioridade="P1",
      extra={"nota": "Implementado em 02/11/2026 (app meetings)."}),
    R("P2-36", "P2 §6; P5 §8; P6 §9", "Histórico de alterações de notas e registros",
      "Nota e entrega auditadas; atividade publicada guarda antes/depois",
      [T("pedagogy", "test_pedagogy", "test_grade_batch_and_audit"),
       T("pedagogy", "test_history_and_ack", "test_editing_published_activity_records_what_changed")], "VALIDADO", prioridade="P2"),
    R("P2-37", "P2 §8.3", "Teste ponta a ponta: conta → cadastro → vínculo → nota → painel → família → solicitação",
      "Cada passo coberto por teste de integração; navegador real com dados de demonstração",
      [T("registry", "test_registry", "test_secretaria_approve_grants_access"),
       T("pedagogy", "test_pedagogy", "test_publish_makes_grades_visible_to_responsavel"),
       T("communication", "test_communication", "test_responsavel_creates_and_notifies_secretaria")], "VALIDADO",
      pendencia="Os passos são testados separadamente; não há um único teste que encadeia os dez passos."),
    R("P2-38", "P2 §8.6", "Testes de desempenho com volume sintético",
      "Medição de tempo e consultas por página com a escola de demonstração",
      ["../docs/VARREDURA_DE_MELHORIAS_2026-11-01.md"], "VERIFICADO", prioridade="P2",
      pendencia="Sem teste de carga com usuários simultâneos; nenhuma afirmação de capacidade é feita."),
    R("P2-39", "P2 §5.33", "Documentação técnica e manual de utilização",
      "README com instalação; manual por perfil; ajuda contextual na plataforma",
      ["README.md", "../Manual de Utilização.md",
       T("core", "test_redesign_round2", "test_every_role_opens_help_and_links_only_to_visible_screens")], "VALIDADO", prioridade="P2"),
    R("P2-40", "P2 §5.30", "Instalação, publicação e manutenção sem custo",
      "iniciar.bat faz backup, migra e sobe o servidor local",
      ["iniciar.bat", "README.md"], "VERIFICADO", prioridade="P2",
      pendencia="Hospedagem pública permanente sem custo não é garantida por nenhum provedor; a plataforma roda na rede da escola."),

    # ================================================================== P3
    R("P3-01", "P3 §5; P6 §4.1; P7 §11; P8 R3; P9 §10", "Design system com tokens centralizados",
      "Cores, tipografia, espaços, raios, sombras e estados em tokens; variáveis usadas existem",
      ["static/css/ds-tokens.css", "../docs/DESIGN_SYSTEM.md",
       T("core", "test_no_external_assets", "test_css_variables_used_in_templates_are_defined")], "VALIDADO", rodada="R3"),
    R("P3-02", "P3 §11; P7 §12; P8 R11", "Contraste adequado (WCAG AA)",
      "Combinações de texto/fundo ≥ 4,5:1 conferidas por teste",
      [T("core", "test_design_tokens", "test_primary_button_text_contrast")], "VALIDADO", rodada="R11"),
    R("P3-03", "P3 §6; P6 §4.2; P7 §6; P8 R4; P9 §9", "Navegação por perfil, menu lateral agrupado, trilha",
      "Menu definido num só lugar por perfil; cada item abre",
      ["apps/core/navigation.py", T("core", "test_navigation", "test_sidebar_renders_items_of_the_role")], "VALIDADO", rodada="R4"),
    R("P3-04", "P3 §6; P6 §4.2", "Seletor entre filhos para responsável com mais de um",
      "Responsável troca de filho sem misturar registros",
      [T("pedagogy", "test_pedagogy", "test_guardian_with_two_children_sees_which_child_each_belongs_to"),
       T("core", "test_redesign_round2", "test_family_cannot_filter_by_someone_elses_child")], "VALIDADO"),
    R("P3-05", "P3 §7.1–7.5; P6 §5; P7 §7; P9 §9.4", "Tela inicial adaptada a cada perfil",
      "Tela 'Hoje' por perfil com o que pede ação",
      ["apps/core/workspace.py", T("core", "test_redesign_round2", "test_teacher_home_shows_todays_attendance_per_class")], "VALIDADO"),
    R("P3-06", "P3 §8; P6 §8", "Gráficos acessíveis, sem 3D, com nome e valores",
      "SVG gerado no servidor com nome acessível e valores; rótulos escapados",
      ["apps/analytics/charts.py", T("analytics", "test_analytics", "test_svg_has_accessible_name_with_values"),
       T("analytics", "test_analytics", "test_bar_chart_escapes_labels")], "VALIDADO"),
    R("P3-07", "P3 §8; P6 §5.4; P7 §7; P9 §5.8", "Sem rankings de estudantes; comparação agregada protegida",
      "Família não vê média da turma; grupos < 5 ocultos",
      [T("core", "test_redesign_round2", "test_family_sees_own_grade_not_class_average"),
       T("analytics", "test_bi", "test_small_groups_are_hidden_in_comparisons")], "VALIDADO", prioridade="P0"),
    R("P3-08", "P3 §9", "Tabelas: ordenação, busca, filtros, paginação, estados vazios",
      "Ordenação por coluna no servidor; filtro mantido na paginação",
      [T("core", "test_redesign_round2", "test_server_sort_and_invented_sort_value"),
       T("pedagogy", "test_pedagogy", "test_family_sees_empty_state_without_activities")], "VALIDADO", prioridade="P2"),
    R("P3-09", "P3 §9", "Tabelas com colunas configuráveis",
      "Usuário escolhe colunas visíveis", [], "DECISÃO", prioridade="P3",
      pendencia="Não implementado: as tabelas têm poucas colunas e empilham no celular (table-stack). "
                "Configurar colunas aumentaria a complexidade sem ganho claro; reavaliar se a escola pedir."),
    R("P3-10", "P3 §9", "Formulários: validação no servidor, mensagens específicas, datas preservadas",
      "Data ISO em todo campo de data; erros por campo",
      [T("core", "test_redesign_round2", "test_every_date_widget_renders_iso"),
       T("core", "test_round3", "test_occurrence_cannot_be_in_the_future")], "VALIDADO", prioridade="P2"),
    R("P3-11", "P3 §9", "Prevenção de envio duplicado de formulário",
      "Reenvio não duplica registro", [T("registry", "test_rollover", "test_resubmitting_does_not_duplicate"),
       T("pedagogy", "test_transfer_and_notices", "test_immediate_publication_notifies_once_even_after_edits")],
      "VALIDADO", prioridade="P3",
      extra={"nota": "Desde 02/11/2026 o ds.js bloqueia o segundo envio de todo formulário POST (no navegador, três "
                     "envios disparados viraram um POST só). O servidor continua protegendo os fluxos críticos."}),
    R("P3-12", "P3 §9; P6 §4.3", "Confirmação antes de ações destrutivas",
      "Diálogo da plataforma (data-confirm) com botão que diz a ação",
      ["static/js/ds.js", "templates/pedagogy/activity_detail.html"], "VERIFICADO", prioridade="P2",
      extra={"nota": "Conferido no navegador em 02/11/2026 (remoção de anexo)."}),
    R("P3-13", "P3 §10; P6 §4.4; P7 §10; P8 R6", "Microinterações discretas e respeito a prefers-reduced-motion",
      "Animações curtas; movimento reduzido respeitado",
      ["static/css/ds-components.css", "../docs/RELATORIO_FINAL_REDESIGN.md"], "VERIFICADO", prioridade="P3"),
    R("P3-14", "P3 §11; P6 §4.5; P7 §12; P9 §14", "Responsividade (celular, tablet, computador)",
      "Sem rolagem lateral a 390 px nas telas conferidas",
      ["../docs/TESTES_VISUAIS_E_FUNCIONAIS.md"], "VERIFICADO", prioridade="P2",
      extra={"nota": "Lista da família e simulador conferidos a 390 px em 02/11/2026."}),
    R("P3-15", "P3 §11; P8 R11", "Acessibilidade: rótulos, foco, hierarquia, sem depender só de cor",
      "Auditoria própria com Playwright; rótulos e cabeçalhos",
      ["../docs/RELATORIO_FINAL_REDESIGN.md", "../docs/AUDITORIA_LIGHTHOUSE_2026-11-02.md"], "PARCIAL", prioridade="P2",
      pendencia="Verificação automática feita em 02/11/2026 (Lighthouse/axe: 100 em 13 páginas de 5 perfis, depois de "
                "corrigir nome do botão de busca, nome do botão de perfil e alvos de toque). Falta teste com leitor "
                "de tela real (NVDA ou Narrador), que nenhuma ferramenta automática substitui."),
    R("P3-16", "P3 §12; P6 §4.3", "Estados de erro, permissão, sessão expirada e página não encontrada",
      "403 explica o motivo; 404 amigável; 500 sem detalhes internos; formulário expirado",
      [T("core", "test_redesign_round2", "test_403_shows_reason_and_way_out"),
       T("core", "test_redesign_round2", "test_404_is_friendly"),
       T("core", "test_redesign_round2", "test_expired_form_page")], "VALIDADO", prioridade="P2"),
    R("P3-17", "P3 §13; P7 §14", "Recursos leves: fontes e ícones locais, sem CDN",
      "Fontes e sprite de ícones servidos pelo próprio servidor",
      ["static/icons/sprite.svg", T("core", "test_no_external_assets", "test_templates_reference_no_external_host")], "VALIDADO"),
    R("P3-18", "P3 §16", "Testes visuais antes/depois e em várias larguras",
      "Capturas registradas", ["../docs/capturas"], "VERIFICADO", prioridade="P3"),
    R("P3-19", "P3 §7.5; P7 §7", "Área do estudante adequada, sem dados administrativos ou disciplinares",
      "Estudante vê tarefas, notas publicadas e frequência própria; não vê ocorrências, observações nem planos",
      [T("registry", "test_student_account", "test_own_dashboard_hides_discipline_and_pedagogical_notes"),
       T("registry", "test_student_account", "test_cannot_list_observations")], "VALIDADO", prioridade="P0"),

    # ================================================================== P4/P10
    R("P4-01", "P4 §6.1 (1, 2, 11)", "Professor publica atividade só para turma e disciplina atribuídas",
      "Par turma+disciplina conferido no servidor",
      [T("pedagogy", "test_pedagogy", "test_teacher_cannot_publish_for_unassigned_class"),
       T("pedagogy", "test_pedagogy", "test_teacher_cannot_mix_class_and_subject_from_different_assignments")], "VALIDADO", prioridade="P0"),
    R("P4-02", "P4 §6.1 (3–9)", "Campos da atividade: título, instruções, datas, materiais, anexos",
      "Formulário com os campos; só título e instruções obrigatórios na edição",
      [T("pedagogy", "test_pedagogy", "test_create_activity_and_submissions")], "VALIDADO"),
    R("P4-03", "P4 §6.1 (10)", "Salvar como rascunho", "Rascunho invisível à família",
      [T("pedagogy", "test_pedagogy", "test_draft_is_invisible_to_guardian")], "VALIDADO"),
    R("P4-04", "P4 §6.1 (12); §6.7", "Editar e cancelar respeitando auditoria e histórico",
      "Edição registra o que mudou; cancelamento mantém registro e entregas",
      [T("pedagogy", "test_history_and_ack", "test_editing_published_activity_records_what_changed"),
       T("pedagogy", "test_pedagogy", "test_cancel_keeps_activity_and_submissions")], "VALIDADO"),
    R("P4-05", "P4 §6.1 (13, 14)", "Consultar anteriores e filtrar por turma, disciplina, data e situação",
      "Filtros na lista do professor; banco de atividades anteriores",
      [T("pedagogy", "test_pedagogy", "test_teacher_can_filter_activities_by_date"),
       T("pedagogy", "test_reuse", "test_bank_lists_own_activities_from_any_year_only")], "VALIDADO"),
    R("P4-06", "P4 §6.1 (15)", "Prévia de como a família verá",
      "Prévia ao lado do formulário e tela de detalhe igual à da família",
      ["templates/pedagogy/activity_form.html", "templates/pedagogy/activity_detail.html"], "VERIFICADO"),
    R("P4-07", "P4 §6.2", "Distribuição automática para todos os ativos da turma, sem cópia por aluno",
      "Um registro; alcança todos os ativos",
      [T("pedagogy", "test_pedagogy", "test_publication_reaches_every_active_student_of_class")], "VALIDADO"),
    R("P4-08", "P4 §6.2", "Quem entra depois recebe as vigentes; quem sai mantém o histórico",
      "Matrícula posterior vê; transferido mantém só o período em que esteve",
      [T("pedagogy", "test_pedagogy", "test_student_enrolled_after_publication_still_sees_activity"),
       T("pedagogy", "test_transfer_and_notices", "test_family_keeps_history_but_not_what_came_after")], "VALIDADO"),
    R("P4-09", "P4 §6.3", "Área da família com dados mínimos, por filho, com estados novas/pendentes/a vencer/vencidas",
      "Cartão por (atividade, filho) com filtro de situação e 'Nova'",
      [T("pedagogy", "test_family_filter", "test_summary_counts_by_situation"),
       T("pedagogy", "test_pedagogy", "test_deadline_states_are_shown_to_family")], "VALIDADO"),
    R("P4-10", "P4 §6.3; §12", "Família só acessa filhos com vínculo; não consulta colegas",
      "Sem vínculo: 403; filtro por aluno alheio: 403",
      [T("pedagogy", "test_pedagogy", "test_guardian_without_link_cannot_open_activity"),
       T("pedagogy", "test_pedagogy", "test_guardian_cannot_filter_by_unrelated_student")], "VALIDADO", prioridade="P0"),
    R("P4-11", "P4 §6.4", "Atividade no registro individual do estudante",
      "Ficha lista atividades atribuídas, sem rascunho",
      [T("pedagogy", "test_pedagogy", "test_activity_appears_in_individual_student_record"),
       T("pedagogy", "test_pedagogy", "test_individual_record_omits_draft")], "VALIDADO"),
    R("P4-12", "P4 §6.5", "Estados compreensíveis; visualização ≠ leitura ≠ conclusão",
      "Situação deriva do prazo; 'Estou ciente' não cria entrega",
      [T("pedagogy", "test_history_and_ack", "test_acknowledging_does_not_complete_the_activity")], "VALIDADO"),
    R("P4-13", "P4 §6.5 (opcional)", "Confirmação de leitura pela família",
      "Botão explícito por filho; professor vê quem confirmou",
      [T("pedagogy", "test_history_and_ack", "test_guardian_acknowledges_for_own_child"),
       T("pedagogy", "test_history_and_ack", "test_teacher_sees_who_is_aware")], "VALIDADO", prioridade="P3"),
    R("P4-14", "P4 §6.6", "Notificação interna sem duplicidade, identificando o filho",
      "Um aviso por (responsável, filho); agendada avisa na data",
      [T("pedagogy", "test_transfer_and_notices", "test_immediate_publication_notifies_once_even_after_edits"),
       T("pedagogy", "test_transfer_and_notices", "test_scheduled_publication_waits_for_its_date")], "VALIDADO"),
    R("P4-15", "P4 §6.8", "Anexos: tipo, tamanho, conteúdo e permissão",
      "Executável e disfarce recusados; família sem vínculo não baixa; anexo removível por quem gerencia",
      [T("pedagogy", "test_pedagogy", "test_renamed_executable_is_rejected"),
       T("pedagogy", "test_pedagogy", "test_guardian_without_link_cannot_download_attachment"),
       T("pedagogy", "test_history_and_ack", "test_others_cannot_remove")], "VALIDADO", prioridade="P0"),
    R("P4-16", "P4 §6.8", "Usuário sem permissão não edita nem cancela",
      "Outro professor recebe 403", [T("pedagogy", "test_pedagogy", "test_other_teacher_cannot_edit_activity")], "VALIDADO", prioridade="P0"),
    R("P4-17", "P4 §10.2", "Turma sem estudantes e atividade sem anexo não quebram",
      "Publicação em turma vazia funciona", [T("pedagogy", "test_pedagogy", "test_class_without_students_publishes_without_error")], "VALIDADO"),

    # ================================================================== P5
    R("P5-01", "P5 §7.1", "Cadastro do trabalho em grupo com campos opcionais",
      "Só título e descrição obrigatórios; prazo não antes da publicação",
      [T("pedagogy", "test_group_work", "test_only_title_and_description_are_required"),
       T("pedagogy", "test_group_work", "test_deadline_before_publication_is_rejected")], "VALIDADO"),
    R("P5-02", "P5 §7.2", "Organização dos grupos a partir dos matriculados; sorteio revisável",
      "Grupo com vários alunos; sorteio não apaga composição publicada",
      [T("pedagogy", "test_group_work", "test_assigns_several_students_at_once"),
       T("pedagogy", "test_group_work", "test_auto_distribution_forms_groups_and_can_be_reviewed"),
       T("pedagogy", "test_group_work", "test_draw_does_not_wipe_published_composition")], "VALIDADO"),
    R("P5-03", "P5 §7.2", "Aluno de outra turma não entra no grupo",
      "Não é oferecido nem aceito", [T("pedagogy", "test_group_work", "test_student_from_another_class_is_not_offered_nor_accepted")], "VALIDADO", prioridade="P0"),
    R("P5-04", "P5 §7.3", "Registro de cada integrante mostra o trabalho, o grupo e os colegas",
      "Ficha do integrante com nome do grupo e colegas",
      [T("pedagogy", "test_group_work", "test_work_appears_in_each_members_record"),
       T("pedagogy", "test_group_work", "test_record_shows_group_name_and_colleagues")], "VALIDADO"),
    R("P5-05", "P5 §7.3; §7.6", "Família vê colegas do grupo do filho e nada privado deles",
      "Não vê composição de outros grupos; nomes não são links",
      [T("pedagogy", "test_group_work", "test_guardian_identifies_the_colleagues_of_the_group"),
       T("pedagogy", "test_group_work", "test_guardian_cannot_reach_private_data_of_colleagues"),
       T("pedagogy", "test_group_work", "test_guardian_does_not_see_the_other_groups_composition")], "VALIDADO", prioridade="P0"),
    R("P5-06", "P5 §7.4", "Trabalho é entidade única; histórico de participação preservado",
      "Um trabalho, não um por aluno; sair do grupo mantém histórico",
      [T("pedagogy", "test_group_work", "test_one_work_is_shared_not_duplicated_per_student"),
       T("pedagogy", "test_group_work", "test_moving_a_student_preserves_the_previous_participation")], "VALIDADO"),
    R("P5-07", "P5 §7.5", "Entrega por grupo ou individual, explícita; sem nota inventada",
      "Modo grupo registra uma linha; modo individual não replica",
      [T("pedagogy", "test_group_work", "test_group_mode_registers_one_row_for_the_group")], "VALIDADO"),
    R("P5-08", "P5 §7.6", "Professor não autorizado não altera grupos (também por POST)",
      "403 em GET e POST", [T("pedagogy", "test_group_work", "test_unauthorized_teacher_cannot_change_groups"),
                            T("pedagogy", "test_group_work", "test_unauthorized_teacher_post_is_also_blocked")], "VALIDADO", prioridade="P0"),
    R("P5-09", "P5 §7.7 (13)", "Cancelamento preserva grupos, integrantes e entregas",
      "Cancelado com motivo, visível à família como cancelado",
      [T("pedagogy", "test_group_work", "test_cancel_preserves_groups_members_and_deliveries")], "VALIDADO"),
    R("P5-10", "P5 §7.7", "Casos: turma vazia, grupo de um, turma inteira, transferido, sem anexo",
      "Cada caso coberto", [T("pedagogy", "test_group_work", "test_class_without_students_does_not_break"),
                            T("pedagogy", "test_group_work", "test_single_member_group_is_allowed"),
                            T("pedagogy", "test_group_work", "test_transferred_student_keeps_participation_history")], "VALIDADO"),
    R("P5-11", "P5 §7.4", "Histórico de alterações do trabalho em grupo após publicação",
      "Mudança de texto/prazo do trabalho publicado guarda antes/depois",
      [T("pedagogy", "test_history_and_ack", "test_editing_published_work_is_recorded_and_shown")], "VALIDADO",
      prioridade="P3", extra={"nota": "GroupWorkChange, 02/11/2026."}),

    # ================================================================== P6
    R("P6-01", "P6 §3; P7 §2; P8 R1", "Pesquisa de referências de design documentada",
      "Referências e princípios registrados", ["../docs/DIRETRIZES_DE_DESIGN_E_REFERENCIAS.md"], "VERIFICADO", prioridade="P3"),
    R("P6-02", "P6 §6.1; P9 §7", "Camada de cálculo única e métricas documentadas",
      "Definição, fórmula, fonte e limitações de cada indicador; metodologia lista todas",
      ["apps/analytics/metrics.py", T("analytics", "test_bi_access", "test_methodology_lists_every_metric")], "VALIDADO"),
    R("P6-03", "P6 §6.2", "Dashboard individual com médias, evolução, distribuição, comparação de períodos",
      "Média ponderada correta; delta com período anterior; nota em branco não é zero",
      [T("analytics", "test_bi", "test_weighted_subject_average_and_overall"),
       T("analytics", "test_bi", "test_delta_against_previous_period"),
       T("analytics", "test_bi", "test_blank_grade_is_not_zero")], "VALIDADO"),
    R("P6-04", "P6 §6.3", "Dashboard da turma (média das médias, distribuição, comparação)",
      "Média da turma é média das médias individuais",
      [T("analytics", "test_bi", "test_class_mean_is_mean_of_student_means_even_with_best_rule"),
       T("analytics", "test_bi_access", "test_class_panel_and_export")], "VALIDADO"),
    R("P6-05", "P6 §6.4", "Comparação temporal entre períodos equivalentes (bimestres do calendário)",
      "Períodos do calendário oficial no seletor; personalizado inválido volta ao padrão",
      [T("analytics", "test_bi", "test_presets_and_invalid_custom")], "VALIDADO"),
    R("P6-06", "P6 §6.6; P9 §12", "Alertas explicáveis com critério, período e ação",
      "Critério transparente; tendência só com pontos suficientes",
      [T("analytics", "test_bi", "test_follow_up_criteria_and_evolution"),
       T("analytics", "test_bi", "test_trend_requires_enough_points")], "VALIDADO"),
    R("P6-07", "P6 §6.7; P7 §9", "Projeções só com dados suficientes; 'dados insuficientes' quando faltar",
      "Sem modelo validado e aprovado, nenhuma probabilidade",
      [T("cognitio", "test_p17", "test_synthetic_recovery_and_no_estimate_without_approval")], "VALIDADO"),
    R("P6-08", "P6 §6.8; P7 §9; P8 R10", "Simulador de cenários de nota e frequência com as regras reais",
      "Nota necessária por fórmula; média simulada; nada é gravado",
      ["apps/analytics/simulator.py", T("analytics", "test_simulator", "test_guardian_simulates_without_saving"),
       T("analytics", "test_simulator", "test_weighted_uses_the_new_weight")], "VALIDADO",
      extra={"nota": "Implementado em 02/11/2026."}),
    R("P6-09", "P6 §6.9", "Atividades e trabalhos em grupo nos dashboards, sem concluir desempenho pela entrega",
      "Cinco estados de entrega e taxas; atividade antes da matrícula não conta",
      [T("analytics", "test_bi", "test_five_states_and_rates"),
       T("analytics", "test_bi", "test_activity_before_student_joined_does_not_reach_him")], "VALIDADO"),
    R("P6-10", "P6 §6.10; P9 §5.10", "Exportação com data, período, critérios e limitações",
      "CSV com cabeçalho de contexto e vazio para dado ausente",
      [T("analytics", "test_bi_access", "test_csv_has_context_header_and_blank_for_missing")], "VALIDADO"),
    R("P6-11", "P6 §7", "Dado ausente nunca vira zero",
      "Sem registro: None/—", [T("analytics", "test_bi", "test_no_records_is_none_not_zero"),
                              T("analytics", "test_analytics", "test_student_without_records_shows_dash_not_zero")], "VALIDADO"),
    R("P6-12", "P6 §5.2", "Professor alterna visão da turma e do aluno, só nas suas disciplinas",
      "Professor só vê disciplinas que leciona; painel do professor só dele",
      [T("academics", "test_teacher_permissions", "test_observations_of_other_subjects_hidden"),
       T("analytics", "test_bi_access", "test_teacher_panel_only_for_the_teacher_himself")], "VALIDADO", prioridade="P0"),

    # ================================================================== P7
    R("P7-01", "P7 §4; P8 R2; P9 §4", "Avaliação de tecnologias (React, Tailwind, ECharts etc.) e decisão justificada",
      "Decisão registrada: Django + templates, sem build e sem CDN",
      ["../docs/ARQUITETURA_FRONTEND.md"], "DECISÃO", prioridade="P2",
      pendencia="React/Next/Tailwind/shadcn/GSAP/Three.js não adotados: exigiriam build, CDN ou servidor Node, "
                "contra o custo zero e a CSP 'self'. Gráficos SVG no servidor substituem ECharts/Plotly."),
    R("P7-02", "P7 §5", "Identidade visual própria (paleta, tipografia, números legíveis)",
      "Design 'Tinta & Papel' com fontes locais", ["static/css/ds-tokens.css", "../docs/DESIGN_SYSTEM.md"], "VERIFICADO"),
    R("P7-03", "P7 §8", "Gráficos: linhas, barras, distribuição, mapa de calor, progresso",
      "Mapa de calor e gráficos nos painéis", ["templates/analytics/bi/_heatmap.html", "apps/analytics/charts.py",
                                               T("analytics", "test_analytics", "test_gauge_marks_danger")], "VALIDADO"),
    R("P7-04", "P7 §8; P9 §11", "Filtros atualizam os dados de fato",
      "Filtro de período e disciplina altera indicadores",
      [T("analytics", "test_bi", "test_draft_and_out_of_period_do_not_count"),
       T("analytics", "test_module_usage", "test_period_filter_applies")], "VALIDADO"),
    R("P7-05", "P7 §9", "Diferenciar observado, calculado, estimado e simulado",
      "Tipo de cada métrica na metodologia; simulador rotulado 'hipótese'",
      ["apps/analytics/metrics.py", "templates/analytics/student_simulator.html"], "VERIFICADO"),
    R("P7-06", "P7 §13", "Dashboards e relatórios com as mesmas permissões das telas",
      "Família e estudante sem comparação com a turma nem qualidade de dados",
      [T("analytics", "test_bi_access", "test_family_and_student_do_not_see_class_comparison_or_quality")], "VALIDADO", prioridade="P0"),
    R("P7-07", "P7 §11", "Sem estilos inline nem scripts inline",
      "Templates e gráficos sem style/script inline; CSP proíbe",
      [T("core", "test_redesign_round2", "test_templates_have_no_inline_style"),
       T("core", "test_redesign_round2", "test_templates_have_no_inline_script_or_handler")], "VALIDADO"),

    # ================================================================== P8
    R("P8-01", "P8 §3", "Matriz de rastreabilidade com evidência",
      "Esta matriz, gerada e conferida por script e por teste",
      ["tools/matriz_requisitos.py", "apps/core/tests/test_requirements_matrix.py"], "VALIDADO"),
    R("P8-02", "P8 R6", "Avaliar Three.js/WebGL para efeitos 3D seletivos",
      "Decisão registrada", [], "DECISÃO", prioridade="P3",
      pendencia="Não adotado: 3D não responde a nenhuma pergunta da escola, pesa no celular e exigiria biblioteca externa."),
    R("P8-03", "P8 R13", "Medição de desempenho (Lighthouse ou equivalente)",
      "Medição registrada: Lighthouse 13.5.0 em 13 páginas de 5 perfis; achados corrigidos",
      ["../docs/AUDITORIA_LIGHTHOUSE_2026-11-02.md", "../docs/VARREDURA_DE_MELHORIAS_2026-11-01.md",
       "tools/lighthouse_flow.mjs", "apps/core/static_serve.py",
       T("core", "test_static", "test_css_and_js_are_gzipped_when_accepted"),
       T("core", "test_static", "test_cache_policy")], "VALIDADO", prioridade="P3",
      extra={"nota": "Autorizado pelo Lucas em 02/11/2026. Acessibilidade 100 e SEO 100 em todas; desempenho 95–100; "
                     "boas práticas 81 só pelo script do Kaspersky injetado por HTTP nesta máquina."}),

    # ================================================================== P9
    R("P9-01", "P9 §5.1", "Visão geral do aluno com indicadores e 'dados insuficientes' quando faltar",
      "Painel mostra '—' sem dado", [T("analytics", "test_analytics", "test_student_without_records_shows_dash_not_zero")], "VALIDADO"),
    R("P9-02", "P9 §5.2", "Clicar no gráfico leva aos registros de origem",
      "Barra da disciplina filtra as avaliações; linha da matriz abre o aluno",
      [T("analytics", "test_bi_access", "test_matrix_row_links_to_student_panel")], "VALIDADO"),
    R("P9-03", "P9 §5.3", "Frequência: percentual, faltas justificadas, atrasos, padrões, sequência",
      "Contagem, percentual, justificadas e maior sequência",
      [T("analytics", "test_bi", "test_counts_percent_justified_streak"),
       T("analytics", "test_bi", "test_near_limit_level")], "VALIDADO"),
    R("P9-04", "P9 §5.3", "Projeção condicional de frequência até o fim do período",
      "Faltas futuras × dias letivos restantes do calendário; máximo de faltas que mantém o mínimo",
      [T("analytics", "test_simulator", "test_projection_and_max_absences"),
       T("analytics", "test_simulator", "test_minimum_unreachable")], "VALIDADO",
      extra={"nota": "Implementado em 02/11/2026."}),
    R("P9-05", "P9 §5.4", "Atividades: atribuídas, no prazo, atrasadas, pendentes, próximas",
      "Cinco estados; entregue com atraso conta como entrega",
      [T("analytics", "test_bi", "test_five_states_and_rates"),
       T("analytics", "test_analytics", "test_activity_stats_late_delivery_counts_as_delivered")], "VALIDADO"),
    R("P9-06", "P9 §5.5", "Ocorrências com cuidado e acesso rigoroso",
      "Estudante não vê; família vê do filho", [T("pedagogy", "test_pedagogy", "test_responsavel_sees_occurences_of_child_only"),
                                               T("registry", "test_student_account", "test_cannot_list_occurrences")], "VALIDADO", prioridade="P0"),
    R("P9-07", "P9 §5.6", "Trajetória: avaliações, frequência, intervenções, reuniões",
      "Linha do tempo com reuniões visíveis a quem pode vê-las",
      [T("meetings", "test_meetings", "test_calendar_and_dashboard_timeline")], "VALIDADO"),
    R("P9-08", "P9 §5.7", "Objetivos individuais com critério, prazo, progresso e histórico",
      "Plano com critério de sucesso e prazo; sinal de prazo vencido e de falta de registro",
      [T("pedagogy", "test_plan_followup", "test_stale_and_overdue_signals"),
       T("pedagogy", "test_plan_followup", "test_list_and_detail_show_the_signals")], "VALIDADO",
      extra={"nota": "Critério, prazo e edição do plano entraram em 02/11/2026."}),
    R("P9-09", "P9 §5.9", "Filtros do dashboard (período, disciplina) com período visível",
      "Período analisado exibido; disciplina filtra avaliações", ["templates/analytics/bi/_filters.html",
                                                                  T("analytics", "test_bi", "test_presets_and_invalid_custom")], "VALIDADO"),
    R("P9-10", "P9 §5.10", "PDF e impressão", "Impressão do navegador gera PDF",
      [T("analytics", "test_analytics", "test_print_view_renders")], "VALIDADO",
      pendencia="PDF via 'Imprimir / Salvar como PDF' do navegador; não há gerador de PDF no servidor (evita dependência)."),
    R("P9-11", "P9 §5.11", "Responsável não consulta outro aluno por URL, filtro ou requisição",
      "403 em painel, simulador e relatório de outro aluno",
      [T("analytics", "test_analytics", "test_guardian_cannot_report_other_student"),
       T("analytics", "test_simulator", "test_access_follows_the_dashboard")], "VALIDADO", prioridade="P0"),
    R("P9-12", "P9 §6.1", "Painel da direção com indicadores e comparação de períodos",
      "Painel institucional restrito", [T("analytics", "test_bi_access", "test_institutional_only_direction_coordination_admin"),
                                        T("analytics", "test_analytics", "test_institutional_indicators")], "VALIDADO"),
    R("P9-13", "P9 §6.1", "Indicadores de utilização dos módulos",
      "Registros por módulo no período e contas que entraram, por perfil, só contagens",
      [T("analytics", "test_module_usage", "test_counts_come_from_the_tables")], "VALIDADO", prioridade="P3",
      extra={"nota": "Implementado em 02/11/2026."}),
    R("P9-14", "P9 §6.2", "Painel da coordenação com escopo da designação",
      "Coordenação restrita vê só as turmas designadas",
      ["apps/coordination/tests/test_coordination.py",
       T("core", "test_link_integrity", "test_restricted_coordinator_calendar_stays_in_scope")], "VALIDADO", prioridade="P0"),
    R("P9-15", "P9 §6.3", "Painel do professor por turma e disciplina autorizadas",
      "Só o próprio professor", [T("analytics", "test_bi_access", "test_teacher_panel_only_for_the_teacher_himself")], "VALIDADO"),
    R("P9-16", "P9 §6.4", "Painel da secretaria", "Restrito à secretaria/gestão",
      [T("analytics", "test_analytics", "test_secretaria_panel_restricted")], "VALIDADO"),
    R("P9-17", "P9 §6.6", "Painel de qualidade dos dados, suspeita ≠ erro confirmado",
      "Detecta notas faltando e chamada parcial", [T("analytics", "test_bi", "test_quality_detects_missing_grades_and_partial_attendance")], "VALIDADO"),
    R("P9-18", "P9 §8.1", "Planejamento de aulas reutilizável, com devolutiva da coordenação",
      "Plano só para o próprio par; rascunho privado; cópia",
      [T("pedagogy", "test_planning", "test_create_only_for_own_pair"),
       T("pedagogy", "test_planning", "test_draft_is_private_and_submit_notifies_only_the_coordinator_in_scope")], "VALIDADO"),
    R("P9-19", "P9 §8.2", "Banco de questões objetivas e discursivas ligadas a habilidades",
      "Questões com tipo e habilidades; respostas por questão", ["apps/cognitio/models.py", "apps/cognitio/tests/test_evidence.py"], "VALIDADO"),
    R("P9-20", "P9 §8.2; §8.3", "Rubricas de avaliação",
      "Rubrica com níveis por critério, ligada à atividade e ao trabalho em grupo, com avaliação visível só à família "
      "do estudante (no trabalho por grupo, identificada como avaliação do grupo)",
      [T("pedagogy", "test_rubrics", "test_scoring_and_family_sees_only_own_child"),
       T("pedagogy", "test_rubrics", "test_rubric_in_use_cannot_be_edited_only_duplicated"),
       T("pedagogy", "test_rubrics", "test_group_mode_scores_the_group_and_family_sees_it_as_group"),
       T("pedagogy", "test_rubrics", "test_individual_mode_scores_each_member"),
       T("pedagogy", "test_rubrics", "test_other_teacher_and_family_cannot_score_and_canceled_is_read_only")],
      "VALIDADO", prioridade="P3",
      extra={"nota": "Atividades de casa em 02/11/2026; trabalho em grupo em 02/11/2026 (rodada seguinte)."}),
    R("P9-21", "P9 §8.2", "Recuperação de avaliações", "Avaliação do tipo recuperação marcada nos painéis",
      [T("analytics", "test_bi", "test_recovery_marked_evaluation")], "VALIDADO"),
    R("P9-22", "P9 §8.3; §15", "Lembretes de prazo e duplicação controlada de atividades",
      "Lembrete por etapa configurável, uma vez; reutilizar cria rascunho",
      [T("communication", "test_reminders", "test_each_configured_stage_reminds_once_and_missed_days_collapse"),
       T("pedagogy", "test_reuse", "test_reuse_creates_draft_with_text_and_attachment_copy")], "VALIDADO"),
    R("P9-23", "P9 §8.5", "Preferências de notificação (silenciar por tipo)",
      "Pessoa silencia tipo, mas não ocorrência", [T("communication", "test_family_events", "test_person_mutes_kind_but_not_occurrence")], "VALIDADO"),
    R("P9-24", "P9 §8.5; §8.9", "Notificações e lembretes de reunião",
      "Convite, remarcação, cancelamento e lembrete da véspera, uma vez",
      [T("meetings", "test_meetings", "test_reminder_goes_once_the_day_before"),
       T("meetings", "test_meetings", "test_reschedule_notifies_again_but_plain_edit_does_not")], "VALIDADO",
      extra={"nota": "Implementado em 02/11/2026."}),
    R("P9-25", "P9 §8.6", "Calendário com visão dia/semana/mês, filtros e reuniões",
      "Agenda, semana e mês; reuniões só para quem pode abrir",
      ["apps/school_calendar/views.py", "apps/school_calendar/tests/test_calendar_window.py",
       T("meetings", "test_meetings", "test_calendar_and_dashboard_timeline")], "VALIDADO"),
    R("P9-26", "P9 §8.7", "Biblioteca pedagógica com etiquetas e favoritos",
      "Biblioteca da escola: busca por texto, etiqueta, código de habilidade; favoritos; reaproveitar numa prova",
      ["apps/study/views_library.py", T("study", "test_study", "test_search_by_tag_and_skill_code_and_favorites"),
       T("study", "test_study", "test_only_shared_and_only_pedagogical_staff")], "VALIDADO", prioridade="P3",
      extra={"nota": "02/11/2026, sobre os materiais de estudo dos conteúdos da prova."}),
    R("P9-27", "P9 §8.9", "Gestão de reuniões e atendimentos com acesso rigoroso a anotações confidenciais",
      "Família vê pauta e registro, nunca anotações da equipe nem encaminhamento interno; escopo da coordenação",
      [T("meetings", "test_meetings", "test_family_sees_summary_but_never_staff_notes"),
       T("meetings", "test_meetings", "test_other_family_and_other_school_are_refused"),
       T("meetings", "test_meetings", "test_direction_sees_all_and_restricted_coordination_only_its_classes")], "VALIDADO", prioridade="P1",
      extra={"nota": "Implementado em 02/11/2026."}),
    R("P9-28", "P9 §8.10", "Gamificação pedagógica responsável",
      "Decisão registrada", [], "DECISÃO", prioridade="P3",
      pendencia="Não implementada: pontos e conquistas tendem a comparar crianças e a premiar quem já vai bem. "
                "O progresso pessoal aparece no painel e nas metas do plano de acompanhamento."),
    R("P9-29", "P9 §8.11", "Central de ajuda: guias, perguntas frequentes e glossário",
      "Ajuda por perfil, com links só para telas visíveis; glossário por perfil",
      [T("core", "test_redesign_round2", "test_every_role_opens_help_and_links_only_to_visible_screens"),
       T("core", "test_help_glossary", "test_glossary_by_role")], "VALIDADO", prioridade="P3",
      extra={"nota": "Glossário entrou em 02/11/2026."}),
    R("P9-30", "P9 §9.1–9.2", "Menus suspensos com teclado, toque e foco",
      "Menu do perfil e notificações acessíveis por teclado",
      ["static/js/ds.js", T("core", "test_navigation", "test_sidebar_renders_items_of_the_role")], "VERIFICADO", prioridade="P2",
      pendencia="Comportamento de teclado conferido manualmente em rodadas anteriores; não há teste automatizado de teclado."),
    R("P9-31", "P9 §15", "Filtros salvos", "Usuário salva uma combinação de filtros e volta a ela pelo menu, "
      "em qualquer computador (guardado na conta, junto com os favoritos)",
      ["static/js/ds.js", "apps/core/views_prefs.py",
       T("core", "test_preferences", "test_saves_and_page_carries_them"),
       T("core", "test_preferences", "test_rejects_external_unknown_or_filterless_urls"),
       T("core", "test_preferences", "test_requires_login_post_and_csrf")], "VALIDADO", prioridade="P3",
      extra={"nota": "Servidor coberto por teste; o lado do navegador (botão, envio e migração do que estava no "
                     "localStorage) foi conferido no navegador, sem teste automatizado de JavaScript."}),
    R("P9-32", "P9 §13", "Retenção e exclusão de dados",
      "Política em três grupos: dado operacional apagável com --aplicar; revisão humana; registro escolar intocado",
      ["apps/core/management/commands/retencao.py", T("core", "test_retention", "test_default_only_reports"),
       T("core", "test_retention", "test_apply_deletes_only_old_read_notices_and_audits")], "VALIDADO", prioridade="P2",
      extra={"nota": "Prazo de guarda do registro escolar continua sendo decisão da escola ou da rede; o comando não o toca."}),
    R("P9-33", "P9 §16 (8)", "Menus funcionam com mouse, toque e teclado (teste)",
      "Roteiro automatizado: menu da conta por clique e teclado, menu lateral no celular, todo item do menu",
      ["tools/qa_menus.mjs"], "VERIFICADO", prioridade="P3",
      pendencia="Executado em 02/11/2026: 6 perfis, 194 páginas, 0 falhas. Roda fora do pytest (exigiria Playwright "
                "como dependência), contra servidor local com cópia do banco."),

    # ================================================================== P18
    R("P18-01", "P18 §6; §6.1", "Modelo de competências e grafo com tipos de relação, fonte e validação",
      "Relações tipadas (pré-requisito, conceitual, facilitador, hipótese...) com situação proposta/validada",
      ["apps/cognitio/models.py", "../docs/EIA_COGNITIO_GRAFO_PRE_REQUISITOS.md",
       T("cognitio", "test_p17", "test_gap_kinds_with_rationale")], "VALIDADO",
      extra={"nota": "Existente desde os Prompts 16 e 17; reaproveitado."}),
    R("P18-02", "P18 §6.2; §8", "Lacunas: confirmada, hipótese, sem evidência; ausência de registro ≠ ausência de aprendizagem",
      "Classificação com fundamento e forma de verificar", [T("cognitio", "test_p17", "test_gap_kinds_with_rationale")],
      "VALIDADO", extra={"nota": "Existente (cognitio.gaps)."}),
    R("P18-03", "P18 §7", "Registro granular por habilidade, com decisão do professor e histórico",
      "Evidências por questão e observação; decisão do professor prevalece até nova evidência; lote com nível "
      "de todos, ajuste por estudante antes de confirmar e indicação de quem ainda não tem registro",
      ["apps/cognitio/models.py", T("cognitio", "test_evidence", "test_observation_for_several_students"),
       T("cognitio", "test_evidence", "test_batch_with_individual_review_and_who_is_missing")], "VALIDADO",
      extra={"nota": "Revisão individual no lote e situação da turma por habilidade: rodada de 02/11/2026."}),
    R("P18-04", "P18 §10.1", "Conteúdos da prova: cadastro com turma, data, tópicos, habilidades, orientações, publicação",
      "Professor cria só para o próprio par; publica com pelo menos um tópico; turma e família avisadas uma vez",
      [T("study", "test_study", "test_teacher_creates_publishes_and_class_is_notified"), T("study", "test_study", "test_teacher_cannot_create_for_other_class")],
      "VALIDADO", prioridade="P1"),
    R("P18-05", "P18 §10.2; §10.3; §10.4", "Materiais: arquivos protegidos, links, vídeos e leituras com validação",
      "URL inválida recusada; leitura sem autor recusada; acesso livre só com link; executável disfarçado recusado",
      [T("study", "test_study", "test_invalid_video_url_is_refused"), T("study", "test_study", "test_reading_needs_enough_information"),
       T("study", "test_study", "test_executable_disguised_as_pdf_is_refused")], "VALIDADO", prioridade="P1"),
    R("P18-06", "P18 §10.5", "Atualizações: material trocado sem link quebrado; data alterada avisada; sem aviso duplicado",
      "Troca registrada no histórico; arquivo retirado não é mais entregue; data segue a avaliação ligada",
      [T("study", "test_study", "test_file_is_protected_and_replacement_is_tracked"), T("study", "test_study", "test_date_change_updates_and_notifies")],
      "VALIDADO", prioridade="P1"),
    R("P18-07", "P18 §10.6", "Experiência do estudante em etapas: o que cai, por onde começar, materiais, como estou, dúvidas",
      "Estudante e família da turma acessam; outra turma e rascunho não; progresso da preparação (o que foi "
      "marcado, o que falta rever, exercícios e dúvidas) na prova e na lista, sem virar nota",
      [T("study", "test_study", "test_family_and_other_class_access"), T("study", "test_study", "test_student_marks_topics_and_asks"),
       T("study", "test_study", "test_preparation_progress_for_student_and_family")], "VALIDADO",
      extra={"nota": "Conferido no navegador a 1280 e 390 px em 02/11/2026."}),
    R("P18-08", "P18 §10.7", "Plano individual de preparação com razão de cada passo; plano geral quando faltam dados",
      "Fundamento com lacuna confirmada primeiro; sem evidência vira verificação; já demonstrado vira revisão",
      [T("study", "test_study", "test_confirmed_gap_in_foundation_comes_first"), T("study", "test_study", "test_no_data_gives_general_plan"),
       T("study", "test_study", "test_missing_evidence_is_a_check_not_a_gap")], "VALIDADO", prioridade="P1"),
    R("P18-09", "P18 §10.8; §20.13", "Autorrelato não é evidência de domínio",
      "Marcar entendi não muda o estado da habilidade", [T("study", "test_study", "test_self_report_does_not_become_evidence")], "VALIDADO"),
    R("P18-10", "P18 §10.8", "Exercícios com correção automática e feedback para preparação",
      "Questões de prática (múltipla escolha) separadas das de prova, com gabarito e explicação após responder; "
      "não geram evidência de habilidade nem nota",
      [T("study", "test_study", "test_teacher_creates_with_compacted_options"),
       T("study", "test_study", "test_student_answers_sees_feedback_and_can_retry"),
       T("study", "test_study", "test_only_the_student_answers_and_teacher_sees_first_try_stats"),
       T("study", "test_study", "test_editing_question_clears_old_answers")], "VALIDADO", prioridade="P3",
      extra={"nota": "Banco separado do EIA-Cognitio de propósito: o gabarito da prática aparece ao estudante, o da "
                     "prova nunca."}),
    R("P18-11", "P18 §10.9", "Painel do professor: autorrelato por tópico, dúvidas, links quebrados, habilidades na turma",
      "Contagens sem ranking; acesso a material não é registrado (decisão)",
      ["templates/study/detail_staff.html", T("study", "test_study", "test_family_reports_broken_link_and_teacher_is_told")], "VALIDADO",
      extra={"nota": "Não há registro de quem abriu qual material: acesso não é estudo (§10.9) e a coleta seria desnecessária (LGPD)."}),
    R("P18-12", "P18 §10.10", "Resultado da prova ligado às habilidades e à recuperação",
      "Análise da prova: habilidades demonstradas nesta prova, erros frequentes, questão a revisar, "
      "pré-requisitos a investigar (com situação da relação), tópicos e materiais a retomar, pequenos grupos, "
      "apoio individual e estratégias; uma questão só não basta para concluir",
      ["apps/cognitio/exam_analysis.py", T("cognitio", "test_exam_analysis", "test_levels_single_question_review_and_absence"),
       T("cognitio", "test_exam_analysis", "test_prerequisites_are_flagged_as_unvalidated_and_counted_by_evidence"),
       T("cognitio", "test_exam_analysis", "test_retake_topics_and_individual_support"),
       T("cognitio", "test_exam_analysis", "test_access_scope_and_audit")],
      "VALIDADO", extra={"nota": "Antes a tela da prova só indicava o caminho; a análise entrou em 02/11/2026 "
                                 "(rodada de reenvio do Prompt 18)."}),
    R("P18-13", "P18 §11", "Recomendação de materiais com motivo, revisável pelo professor",
      "Cada passo do plano mostra os materiais ligados às habilidades e o porquê; decisão do professor muda o plano",
      [T("study", "test_study", "test_teacher_decision_changes_the_plan")], "VALIDADO"),
    R("P18-14", "P18 §14", "Permissões por papel: secretaria sem acesso; família só dos filhos; professor do par",
      "403 para secretaria, outra turma e outro professor; plano por estudante auditado",
      [T("study", "test_study", "test_teacher_view_of_student_plan_is_scoped_and_audited"), T("study", "test_study", "test_family_and_other_class_access")],
      "VALIDADO", prioridade="P0"),
    R("P18-15", "P18 §17", "Família só recebe personalização se a escola ligar o compartilhamento, em linguagem própria",
      "Sem compartilhamento: plano geral; com: sem a palavra dificuldade, sem porcentagem",
      [T("study", "test_study", "test_family_plan_follows_school_sharing_rule")], "VALIDADO", prioridade="P0"),
    R("P18-16", "P18 §20.19", "Dois usuários editando o mesmo conteúdo",
      "Trava otimista: quem salva com versão antiga é avisado e nada é gravado",
      [T("study", "test_study", "test_two_people_editing_the_same_guide")], "VALIDADO"),
    R("P18-17", "P18 §20.27", "Arquivamento sem perda de histórico", "Arquivar tira das listas; dúvidas e histórico ficam",
      [T("study", "test_study", "test_archive_keeps_history")], "VALIDADO"),
    R("P18-18", "P18 §10.1", "Reutilizar conteúdos em outra turma", "Cópia como rascunho, sem dúvidas e marcações",
      [T("study", "test_study", "test_reuse_copies_structure_to_own_class_as_draft")], "VALIDADO"),
    R("P18-19", "P18 §16", "Indicadores: conteúdos de prova e dúvidas na utilização da plataforma",
      "Contagens no painel institucional", ["apps/analytics/bi.py",
       T("analytics", "test_module_usage", "test_counts_come_from_the_tables")], "VALIDADO", prioridade="P3"),
    R("P18-21", "P18 §12", "Tipo de intervenção (reforço, retomada, recuperação, aprofundamento, enriquecimento) e formato",
      "Tipo registrado na intervenção; formato (individual, pequeno grupo, turma) tirado dos estudantes marcados",
      [T("cognitio", "test_intelligence", "test_intervention_kind_and_grouping")], "VALIDADO", prioridade="P2"),
    R("P18-20", "P18 §4", "Referencial científico verificado para a nova área",
      "Referências conferidas; nenhuma inventada", ["../docs/ESPECIFICACAO_CONTEUDOS_DA_PROVA.md"], "VERIFICADO",
      extra={"nota": "Dunning, Heath e Suls (2004) com DOI conferido; Dunlosky et al. (2013) conferido sem DOI."}),
]


# Prompts 13 a 17 (acrescentados pelo Prompt 20): módulo próprio, mesma conferência.
_spec = importlib.util.spec_from_file_location("matriz_p13_p17", Path(__file__).resolve().parent / "matriz_p13_p17.py")
_p13 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_p13)
PROMPTS.update(_p13.PROMPTS)
REQS += _p13.build(R)


def _check_evidence(path):
    """'' se a evidência existe; senão, o motivo."""
    file_part, _, test = path.partition("::")
    target = (ROOT / file_part).resolve()
    if not target.exists():
        return f"não existe: {file_part}"
    if test:
        text = target.read_text(encoding="utf-8")
        if not re.search(rf"def {re.escape(test)}\b", text):
            return f"teste não encontrado: {path}"
    return ""


def validate():
    errors = []
    ids = Counter(r.id for r in REQS)
    errors += [f"ID repetido: {i}" for i, n in ids.items() if n > 1]
    for r in REQS:
        if r.situacao not in STATES:
            errors.append(f"{r.id}: situação inválida {r.situacao!r}")
        for ev in r.evidencia:
            why = _check_evidence(ev)
            if why:
                errors.append(f"{r.id}: {why}")
        if r.situacao == "VALIDADO" and not any("::" in e or "/tests/" in e for e in r.evidencia):
            errors.append(f"{r.id}: VALIDADO sem teste automatizado citado")
        if r.situacao in ("PARCIAL", "DECISÃO", "NÃO IMPLEMENTADO", "BLOQUEADO") and not r.pendencia:
            errors.append(f"{r.id}: {r.situacao} sem pendência/razão")
    return errors


def render():
    by_state = Counter(r.situacao for r in REQS)
    by_prompt = {}
    for r in REQS:
        by_prompt.setdefault(r.id.split("-")[0], Counter())[r.situacao] += 1
    out = [
        "# Matriz mestra de requisitos (Prompts 11 e 20)",
        "",
        "Gerada por `plataforma-escolar/tools/matriz_requisitos.py`. Não edite à mão: edite o script e rode-o.",
        "Cada evidência foi conferida pelo script (o arquivo existe; o teste citado existe no arquivo), e o teste",
        "`apps/core/tests/test_requirements_matrix.py` repete essa conferência a cada execução da suíte.",
        "",
        "Os Prompts 4 e 10 têm o mesmo texto; seus requisitos aparecem uma vez, com o prefixo P4.",
        "Os Prompts 13 a 17 entraram pelo Prompt 20 (02/11/2026), em `tools/matriz_p13_p17.py`.",
        "Requisitos repetidos em vários prompts aparecem uma vez, com todas as origens na coluna Origem.",
        "",
        "## Situações",
        "",
        "| Situação | Significado | Quantidade |",
        "|---|---|---|",
    ]
    meaning = {
        "VALIDADO": "implementado e coberto por teste automatizado que passa",
        "VERIFICADO": "implementado e conferido no navegador ou por inspeção, sem teste automatizado",
        "PARCIAL": "existe, mas não cobre tudo (ver pendência)",
        "DECISÃO": "não implementado de propósito (ver razão)",
        "NÃO IMPLEMENTADO": "falta, sem impedimento técnico",
        "BLOQUEADO": "depende de algo fora do ambiente",
    }
    for s in STATES:
        out.append(f"| {s} | {meaning[s]} | {by_state.get(s, 0)} |")
    out += ["", f"Total: **{len(REQS)}** requisitos.", "", "## Por prompt", "",
            "| Prompt | Arquivo | " + " | ".join(STATES) + " |", "|---|---|" + "---|" * len(STATES)]
    for p, name in PROMPTS.items():
        c = by_prompt.get(p, Counter())
        out.append(f"| {p} | {name} | " + " | ".join(str(c.get(s, 0)) for s in STATES) + " |")
    out += ["", "## Requisitos", "",
            "| ID | Origem | Requisito | Critério de aceitação | Evidência | Situação | Prioridade | Pendência / observação |",
            "|---|---|---|---|---|---|---|---|"]
    for r in REQS:
        ev = "<br>".join(f"`{e}`" for e in r.evidencia) or "—"
        note = r.pendencia or r.extra.get("nota", "")
        if r.pendencia and r.extra.get("nota"):
            note = f"{r.extra['nota']} {r.pendencia}"
        cells = [r.id, r.origem, r.requisito, r.criterio, ev, f"**{r.situacao}**", r.prioridade, note or "—"]
        out.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    out.append("")
    return "\n".join(out)


def main(argv):
    errors = validate()
    if errors:
        print("Matriz com evidência inválida:")
        for e in errors:
            print(" -", e)
        return 1
    if "--check" in argv:
        print(f"Matriz conferida: {len(REQS)} requisitos, evidências existentes.")
        return 0
    OUT.write_text(render(), encoding="utf-8")
    print(f"Gravado {OUT} ({len(REQS)} requisitos).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
