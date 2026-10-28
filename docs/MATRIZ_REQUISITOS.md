# MATRIZ MESTRA DE REQUISITOS E CONFORMIDADE
**Projeto:** Plataforma Escolar Integrada  
**Documento Base:** Prompt 10 (Mega Prompt de Auditoria Profunda e Evolução) e Consolidação de Prompts 1 a 11  
**Atualizado em:** 28 de Outubro de 2026

---

## 1. Classificação dos Requisitos (10 Categorias Obrigatórias)

### Categoria 1: Requisitos Funcionais Obrigatórios
| ID | Requisito | Evidência no Projeto | Estado | Testes de Validação |
|:---|:---|:---|:---|:---|
| RF01 | Cadastro de estudantes com dados pedagógicos, foto e prontuário completo | `apps.registry.models.Student`, `views.student_detail` | **Implementado e validado** | `apps/registry/tests/test_registry.py` |
| RF02 | Vínculo de responsáveis com estudantes sujeito a aprovação da secretaria | `apps.registry.models.GuardianLink`, `views.link_approve` | **Implementado e validado** | `test_guardian_link_approval` |
| RF03 | Matrícula do estudante em turma e ano letivo com rastreamento de entrada/saída | `apps.registry.models.Enrollment`, `views.enrollment_create` | **Implementado e validado** | `test_after_transfer.py` |
| RF04 | Atribuição de professores por turma e disciplina (`TeacherAssignment`) | `apps.academics.models.TeacherAssignment` | **Implementado e validado** | `test_academics.py` |
| RF05 | Lançamento de avaliações e notas com fórmula de média configurável | `apps.pedagogy.models.Evaluation`, `Grade`, `AcademicRule` | **Implementado e validado** | `test_pedagogy.py` |
| RF06 | Registro de frequência diária (presença, atraso, falta) com cálculo de percentual | `apps.pedagogy.models.AttendanceRecord`, `views.attendance_register` | **Implementado e validado** | `test_pedagogy.py` |
| RF07 | Justificativas de falta enviadas pela família com análise pela secretaria | `apps.pedagogy.models.AbsenceJustification`, `views.justification_resolve` | **Implementado e validado** | `test_pedagogy.py` |
| RF08 | Registro de ocorrências disciplinares e observações pedagógicas | `apps.pedagogy.models.Occurrence`, `PedagogicalObservation` | **Implementado e validado** | `test_pedagogy.py` |
| RF09 | Planos de intervenção/acompanhamento individual com notas de evolução | `apps.pedagogy.models.InterventionPlan`, `PlanNote` | **Implementado e validado** | `test_pedagogy.py` |
| RF10 | Central de comunicação interna (mensagens, comunicados, solicitações) | `apps.communication.models.MessageThread`, `Announcement`, `ServiceRequest` | **Implementado e validado** | `test_communication.py` |

---

### Categoria 2: Requisitos de Negócio e Pedagógicos
| ID | Requisito | Evidência no Projeto | Estado | Testes de Validação |
|:---|:---|:---|:---|:---|
| RN01 | Fórmulas de cálculo de média flexíveis por disciplina (aritmética, ponderada, melhor nota, soma) | `apps.pedagogy.models.AcademicRule`, `services.subject_averages` | **Implementado e validado** | `test_academic_rule_calculation` |
| RN02 | Notas de atividades de casa NÃO alteram a média da disciplina | `apps.pedagogy.models.Submission.grade` campo isolado | **Implementado e validado** | `test_activity_grade_does_not_change_subject_average` |
| RN03 | Aluno transferido de turma mantém integralmente histórico de notas e atividades | `apps.pedagogy.access.enrollment_window_q`, `_left_class` | **Implementado e validado** | `test_transferred_student_keeps_activity_history`, `test_after_transfer.py` |
| RN04 | Justificativas aprovadas pela secretaria não apagam falta oficial (preserva verdade histórica) | `AbsenceJustification` não altera `AttendanceRecord` | **Implementado e validado** | `test_justification_does_not_alter_attendance` |
| RN05 | Ocorrências e anotações disciplinares restritas à equipe e responsáveis (ocultas do estudante) | `apps.pedagogy.access.can_view_occurrences`, RBAC | **Implementado e validado** | `test_student_cannot_view_occurrences` |

---

### Categoria 3: Requisitos de Interface, Design e Experiência do Usuário (UI/UX)
| ID | Requisito | Evidência no Projeto | Estado | Testes de Validação |
|:---|:---|:---|:---|:---|
| RU01 | Identidade visual moderna e consistente com suporte a tema claro e escuro | `templates/base.html`, `static/css/premium.css`, `static/js/theme.js` | **Implementado e validado** | Validação visual de CSS e testes de renderização |
| RU02 | Barra de navegação com menus contextualizados e sem duplicações | `templates/base.html` corrigido (removido link duplicado de Início) | **Implementado e validado** | Testes de status code e renderização |
| RU03 | Ações rápidas personalizadas na Home para todos os perfis (Direção, Coordenação, Professor, etc.) | `templates/home.html` enriquecido com cards para Direção, Coordenação e Professor | **Implementado e validado** | Testes de contexto de home por perfil |
| RU04 | Modo de prévia da atividade de casa exatamente como a família visualiza | `templates/pedagogy/activity_detail.html` com banner de prévia | **Implementado e validado** | Testes de renderização de activity_detail |
| RU05 | Ações rápidas em lote para marcação de entregas de atividades pelo professor | `templates/pedagogy/activity_submissions.html` com botões rápidos | **Implementado e validado** | Testes de template |
| RU06 | Chips visuais semânticos para estados de atividades, notas e frequências | `templates/partials`, classes CSS `.chip`, `.chip-state` | **Implementado e validado** | Testes de templates |

---

### Categoria 4: Requisitos Técnicos e Arquiteturais
| ID | Requisito | Evidência no Projeto | Estado | Testes de Validação |
|:---|:---|:---|:---|:---|
| RT01 | Arquitetura modular Django com separação limpa de responsabilidades (`apps/*`) | `apps/core`, `academics`, `registry`, `pedagogy`, `communication`, `analytics` | **Implementado e validado** | `manage.py check` sem advertências |
| RT02 | Eliminação de consultas N+1 nos relatórios e listagens | Otimização de `_r_atividades_pendentes` com prefetch/queries em lote | **Implementado e validado** | `test_report_atividades_pendentes_filters_drafts_and_delivered` |
| RT03 | Configuração estrita de testes com Pytest focado nas aplicações | `pytest.ini` configurado com `testpaths = apps` | **Implementado e validado** | Execução limpa do Pytest |
| RT04 | Migrações consistentes sem perda de dados existentes | Migrações Django 0001 a 0005 em todas as apps aplicadas | **Implementado e validado** | `manage.py showmigrations` 100% OK |

---

### Categoria 5: Segurança, Privacidade e LGPD
| ID | Requisito | Evidência no Projeto | Estado | Testes de Validação |
|:---|:---|:---|:---|:---|
| RS01 | Autorização e verificação de escopo estritamente no servidor (backend) | `apps.pedagogy.access`, `apps.analytics.access`, `apps.registry.access` | **Implementado e validado** | `test_guardian_without_link_cannot_open_activity` |
| RS02 | Responsável não pode acessar atividades, notas ou prontuários de outros alunos | Checagem de vínculo em `activity_detail`, `activity_list`, `student_detail` | **Implementado e validado** | `test_guardian_child_isolation` |
| RS03 | Download de anexos protegido por view autenticada com validação de vínculo | `activity_attachment`, `groupwork_attachment` via `FileResponse` | **Implementado e validado** | `test_activity_attachment_permission` |
| RS04 | Validação estrita de upload de arquivos (tipo MIME, extensão, tamanho máx. 10MB) | `apps.core.uploads.validate_attachment`, `validate_attachment_content` | **Implementado e validado** | `test_attachment_upload_security` |
| RS05 | Trilha de auditoria para operações críticas (`AuditLog`) | `apps.core.models.AuditLog`, chamadas `_log()` em views | **Implementado e validado** | `test_audit_log_creation` |

---

### Categoria 6: Desempenho, Estabilidade e Confiabilidade
| ID | Requisito | Evidência no Projeto | Estado | Testes de Validação |
|:---|:---|:---|:---|:---|
| RD01 | Parâmetros de URL inválidos não causam erro 500 | `apps.core.params.id_param`, parsing seguro de inteiros e datas | **Implementado e validado** | `test_malformed_params.py` |
| RD02 | Transações atômicas para gravação de atividades, entregas e notas | `transaction.atomic()` em todas as operações de mutação | **Implementado e validado** | `test_pedagogy.py` |
| RD03 | Otimização de consultas em relatórios analíticos | Pré-carregamento de entregas em conjunto (`delivered_pairs`) | **Implementado e validado** | `test_analytics.py` |

---

### Categoria 7: Hospedagem, Instalação, Manutenção e Custo Zero
| ID | Requisito | Evidência no Projeto | Estado | Testes de Validação |
|:---|:---|:---|:---|:---|
| RC01 | Custo zero absoluto: operação independente de serviços em nuvem pagos | Uso de Django, SQLite nativo, CSS/JS locais e CDNs públicas | **Implementado e validado** | Auditoria de dependências |
| RC02 | Comando de inicialização e dados de demonstração sintéticos | `manage.py seeddemo`, `manage.py initadmin` | **Implementado e validado** | Execução e validação de `seeddemo` |
| RC03 | Backup local do banco de dados | `manage.py backupdb` em `apps/core/management/commands/backupdb.py` | **Implementado e validado** | Verificação do comando de backup |

---

### Categoria 8: Atividades de Casa por Turma (Funcionalidade Prioritária - Prompt 10)
| ID | Sub-Requisito | Evidência no Projeto | Estado | Testes de Validação |
|:---|:---|:---|:---|:---|:---|
| AH01 | Professor cadastra atividade escolhendo turma e disciplina autorizadas | `ActivityForm`, validação em `clean()` contra `TeacherAssignment` | **Implementado e validado** | `test_create_activity_and_submissions` |
| AH02 | Campos pedagógicos completos: título, instruções, materiais, critérios, datas | `Activity` model: `title`, `description`, `materials`, `criteria`, `published_date`, `deadline`, `class_date` | **Implementado e validado** | `test_create_activity_and_submissions` |
| AH03 | Suporte a anexos de apoio validados | `ActivityAttachment`, `MultipleFileField` | **Implementado e validado** | `test_activity_attachments` |
| AH04 | Salvar como rascunho ou publicar para a turma | Botões em `activity_form.html`, status `DRAFT` vs `PUBLISHED` | **Implementado e validado** | `test_scheduled_activity_hidden_until_publication_date` |
| AH05 | Distribuição automática para todos os estudantes da turma (registro único) | Modelo relacional centralizado: `Activity.class_group` | **Implementado e validado** | `test_publication_reaches_every_active_student_of_class` |
| AH06 | Tratamento correto de novas matrículas e transferências de turma | Consulta dinâmica por período de matrícula (`enrollment_window_q`) | **Implementado e validado** | `test_student_enrolled_after_publication_still_sees_activity`, `test_transferred_student_keeps_activity_history` |
| AH07 | Área exclusiva de atividades para pais e responsáveis com filtros de situação | `templates/pedagogy/activity_family.html`, filtro por filho e situação | **Implementado e validado** | `test_responsavel_sees_activities_of_child` |
| AH08 | Exibição da atividade no prontuário individual do aluno | `templates/registry/student_detail.html` aba "Pedagógico" | **Implementado e validado** | `test_activity_appears_in_individual_student_record` |
| AH09 | Edição e cancelamento com registro de motivo e preservação histórica | `activity_cancel` view com `Activity.cancel_reason`, sem exclusão física | **Implementado e validado** | `test_cancel_keeps_activity_and_submissions`, `test_canceled_activity_still_visible_to_family_as_canceled` |
| AH10 | Controle de entregas pelo professor com nota opcional e observação | `activity_submissions` view, modelo `Submission` | **Implementado e validado** | `test_create_activity_and_submissions` |
| AH11 | Ações rápidas em lote para entregas ("Marcar todos como Entregue") | Implementado em `activity_submissions.html` com JS reativo | **Implementado e validado** | Teste de interface |
| AH12 | Prévia explícita da visualização dos pais para o professor | Banner e layout espelhado em `activity_detail.html` | **Implementado e validado** | Teste de renderização |
| AH13 | Notificações internas automáticas no envio e cancelamento | `apps.communication.services.announce_publication`, `notify_publication_canceled` | **Implementado e validado** | `test_communication.py` |

---

### Categoria 9: Trabalhos em Grupo com Participantes (Prompt 5)
| ID | Requisito | Evidência no Projeto | Estado | Testes de Validação |
|:---|:---|:---|:---|:---|
| TG01 | Cadastro de trabalho em grupo pela turma e disciplina | `apps.pedagogy.models.GroupWork`, `GroupWorkForm` | **Implementado e validado** | `test_group_work.py` |
| TG02 | Organização e composição dos grupos com histórico de membros | `WorkGroup`, `WorkGroupMember` com `removed_at` | **Implementado e validado** | `test_group_work.py` |
| TG03 | Modos de entrega: por grupo ou individual | `GroupWork.DeliveryMode`, `GroupWorkDelivery` com constraints únicas | **Implementado e validado** | `test_group_work.py` |
| TG04 | Visualização pelos responsáveis dos integrantes do grupo do filho | `groupwork_family.html`, `student_detail.html` com colegas do grupo | **Implementado e validado** | `test_group_work.py` |

---

### Categoria 10: Melhorias Implementadas nesta Auditoria (Prompt 10)
| ID | Melhoria | Módulo Afetado | Benefício Obtido | Validação |
|:---|:---|:---|:---|:---|
| MI01 | Otimização de desempenho no relatório de atividades pendentes (eliminação de consultas N+1) | `apps/analytics/reports.py` | Redução drástica no tempo de resposta e consumo de CPU no banco | Testado com `test_report_atividades_pendentes_filters_drafts_and_delivered` |
| MI02 | Correção da filtragem do relatório de pendências (exclusão de rascunhos e atividades canceladas) | `apps/analytics/reports.py` | Integridade das métricas: alunos não são cobrados por rascunhos ou tarefas canceladas | Teste unitário aprovado |
| MI03 | Remoção de link duplicado de "Início" na barra de navegação superior | `templates/base.html` | Interface mais limpa, ergonômica e sem redundâncias visuais | Validado em renderização |
| MI04 | Correção de tag HTML `</div>` órfã na página inicial | `templates/home.html` | Conformidade estrita com o padrão HTML5, evitando bugs de renderização no DOM | Validado em renderização |
| MI05 | Enriquecimento dos painéis da Home para Direção, Coordenação e Professor | `templates/home.html` | Acesso em 1 clique ao Painel Institucional, Relatórios, Turmas, Tarefas e Trabalhos em Grupo | Validado em múltiplos papéis |
| MI06 | Adição de botões rápidos de entrega em lote para o professor | `templates/pedagogy/activity_submissions.html` | Economia de tempo para professores ao lançar tarefas de turmas grandes | Validado no template |
| MI07 | Banner didático de Modo de Prévia na visualização de detalhes da atividade | `templates/pedagogy/activity_detail.html` | Atende explicitamente o item 15 da §6.1 do Prompt 10 | Validado no template |
| MI08 | Configuração estrita do pytest para evitar erro de decodificação de logs no root | `pytest.ini` (`testpaths = apps`) | Execução rápida e resiliente da suíte de testes automatizados | `pytest` executando com 100% de sucesso |
