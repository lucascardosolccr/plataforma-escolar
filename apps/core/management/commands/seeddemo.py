"""Escola de demonstração com dados sintéticos.

Cria uma escola SEPARADA (código `demo`), e não registros soltos na escola
real. A plataforma já isola os dados por escola, então essa separação é o que
garante que a demonstração nunca se misture com a operação — requisito da
seção 22 do Prompt 1 ("identifique-os claramente e mantenha-os separados dos
dados de produção") e da seção 13 (dados sintéticos, nunca de estudantes
reais).

Todos os nomes abaixo são inventados.
"""

import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.core.models import AuditLog, Role, School, User
from apps.pedagogy.models import (
    Activity,
    AttendanceRecord,
    Evaluation,
    Grade,
    GroupWork,
    GroupWorkDelivery,
    Occurrence,
    PedagogicalObservation,
    SchoolConfig,
    Submission,
    WorkGroup,
    WorkGroupMember,
)
from apps.registry.models import Enrollment, GuardianLink, GuardianProfile, Student

DEMO_CODE = "demo"
DEMO_PASSWORD = "demo-senha-forte-2026"

NOMES = [
    "Alice", "Benjamim", "Cecília", "Davi", "Eloá", "Felipe", "Gabriela",
    "Heitor", "Isadora", "João", "Kaique", "Lívia", "Miguel", "Nina",
    "Otávio", "Pietra", "Quésia", "Rafael", "Sofia", "Théo", "Úrsula",
    "Vicente", "Wanda", "Yasmin", "Zeca", "Antônia", "Bruno", "Clara",
    "Diogo", "Esther", "Fábio", "Giovana", "Henrique", "Ingrid", "Jonas",
]
SOBRENOMES = [
    "Almeida", "Barbosa", "Carvalho", "Dias", "Esteves", "Farias", "Gomes",
    "Henriques", "Teixeira", "Lopes", "Moreira", "Nogueira", "Pacheco",
    "Queiroz", "Ribeiro", "Santana", "Tavares", "Vieira",
]
DISCIPLINAS = [
    "Matemática", "Língua Portuguesa", "Ciências", "História",
    "Geografia", "Arte", "Educação Física",
]
TAREFAS = [
    ("Exercícios de fração", "Resolver os itens 1 a 12 da página 48, mostrando o cálculo."),
    ("Leitura do capítulo 3", "Ler o capítulo e anotar três perguntas sobre o texto."),
    ("Experimento da germinação", "Plantar o feijão no algodão e anotar o que muda a cada dia."),
    ("Linha do tempo do bairro", "Montar a linha do tempo com cinco acontecimentos."),
    ("Mapa das regiões", "Pintar e legendar as cinco regiões no mapa recebido."),
    ("Desenho de observação", "Desenhar um objeto da casa olhando para ele, sem copiar imagem."),
    ("Ficha de alongamento", "Fazer os alongamentos da ficha e marcar os dias."),
    ("Tabuada do 7 e do 8", "Treinar e pedir a alguém da casa para conferir."),
    ("Reescrita do final", "Reescrever o final da história com outro desfecho."),
    ("Caça-palavras de sinônimos", "Completar e escrever uma frase com três das palavras."),
]
TRABALHOS = [
    (
        "Pesquisa sobre o meio ambiente",
        "Pesquisar a nascente mais próxima da escola, registrar em fotos ou "
        "desenhos e montar um cartaz explicando o que o grupo encontrou.",
        "Cartaz e apresentação de 10 minutos",
    ),
    (
        "Linha do tempo da cidade",
        "Montar uma linha do tempo com cinco acontecimentos importantes da "
        "cidade, dizendo onde o grupo encontrou cada informação.",
        "Painel em cartolina",
    ),
    (
        "Feira de experimentos",
        "Escolher um experimento simples, repetir três vezes, anotar o que "
        "mudou em cada tentativa e explicar o resultado para a turma.",
        "Demonstração ao vivo",
    ),
    (
        "Mapa do bairro",
        "Desenhar o mapa do bairro marcando escola, praça e pontos de ônibus, "
        "e escrever uma legenda.",
        "Mapa desenhado à mão",
    ),
    (
        "Jornal da turma",
        "Escrever quatro notícias curtas sobre a escola e organizar em formato "
        "de jornal, com título e autoria de cada texto.",
        "Jornal impresso de duas páginas",
    ),
    (
        "Leitura dramatizada",
        "Escolher um trecho do livro lido no bimestre e preparar uma leitura "
        "dramatizada, dividindo as falas entre os integrantes.",
        "Apresentação em sala",
    ),
]


class Command(BaseCommand):
    help = (
        "Cria a escola de demonstração 'demo' com dados sintéticos, separada "
        "da escola real. Use --limpar para remover tudo."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limpar",
            action="store_true",
            help="Remove a escola de demonstração e tudo que pertence a ela.",
        )
        parser.add_argument(
            "--estudantes", type=int, default=72,
            help="Quantos estudantes criar (padrão: 72).",
        )
        parser.add_argument(
            "--semente", type=int, default=2026,
            help="Semente aleatória, para o resultado ser reproduzível.",
        )

    def handle(self, *args, **options):
        if options["limpar"]:
            return self._limpar()
        self._criar(options["estudantes"], options["semente"])

    # ---------------------------------------------------------------- limpar
    def _limpar(self):
        """Remove a escola de demonstração inteira.

        A ordem abaixo é obrigatória: várias chaves estrangeiras são PROTECT
        (``Evaluation.class_group``, ``Enrollment.school_year``, entre outras),
        então apagar a turma antes dos registros pedagógicos levanta
        ProtectedError e deixa a escola pela metade.
        """
        from apps.analytics.models import SchoolGoal
        from apps.booking.models import Booking, Resource
        from apps.care.models import (
            AuthorizedPickup,
            DepartureNotice,
            EmergencyContact,
            HealthIncident,
            HealthRecord,
            MedicationDose,
            MedicationRequest,
            PickupRecord,
        )
        from apps.cognitio.models import (
            AnalysisFeedback,
            InterventionStrategy,
            LearningAlert,
            LearningIntervention,
            LearningTrail,
            MasteryScale,
            ModelRun,
            Question,
            QuestionResponse,
            QuestionSkill,
            SkillEvidence,
            SkillJudgment,
            SkillObservation,
            SkillRelation,
            TextAnalysis,
        )
        from apps.communication.models import (
            Announcement,
            Authorization,
            AuthorizationResponse,
            Message,
            Notification,
            Poll,
            PollVote,
            ServiceRequest,
            Thread,
        )
        from apps.coordination.models import CoordinationRecord
        from apps.curriculum.models import LearningEvidence
        from apps.gate.models import GateEvent, GateSettings, StudentCard
        from apps.inclusion.models import (
            SupportCase,
            SupportCategory,
            SupportDocument,
            SupportEvent,
            SupportNeed,
            SupportPlan,
            SupportPlanReview,
            SupportPlanVersion,
            SupportRequest,
            SupportSettings,
        )
        from apps.library.models import Book, LibrarySettings, Loan, Reservation
        from apps.longitudinal.models import PriorGrade, PriorYear, YearResult
        from apps.lostfound.models import Claim, FoundItem
        from apps.meetings.models import (
            Meeting,
            MeetingFollowUp,
            OfficeHours,
            OfficeSlot,
        )
        from apps.paperwork.models import RequiredDocument, StudentDocument
        from apps.pedagogy.models import (
            AbsenceJustification,
            AcademicRule,
            ActiveSearchAction,
            GroupWorkRubricScore,
            InterventionPlan,
            LessonPlan,
            LessonPlanReview,
            LessonRecord,
            Rubric,
            RubricCriterion,
            RubricDescriptor,
            RubricLevel,
            RubricScore,
        )
        from apps.reenroll.models import Answer, Campaign
        from apps.registry.models import GuardianProfile
        from apps.rotina.models import ClassSchedule, MealMenu
        from apps.school_calendar.models import (
            CalendarEvent,
            CalendarPeriod,
            CalendarPublication,
        )
        from apps.study.models import (
            ExamGuide,
            ExamTopic,
            GuideUpdate,
            LibraryFavorite,
            PracticeAttempt,
            PracticeQuestion,
            StudyMaterial,
            StudyQuestion,
            TopicCheck,
        )
        from apps.supplies.models import SupplyCheck, SupplyItem, SupplyList
        from apps.workshops.models import Signup, Workshop

        school = School.objects.filter(code=DEMO_CODE).first()
        if not school:
            self.stdout.write("Nada a remover: escola de demonstração não existe.")
            return

        contas = list(User.objects.filter(school=school).values_list("pk", flat=True))
        estudantes = list(
            Student.objects.filter(school=school).values_list("pk", flat=True)
        )

        with transaction.atomic():
            # 0. Módulos complementares da demonstração. Removidos antes de tudo,
            #    para liberar turmas, disciplinas, matrículas e estudantes dos
            #    PROTECT (biblioteca, reuniões, portaria, conteúdos de prova...).
            #    Itens curriculares nacionais (school nulo) nunca são tocados.
            PracticeAttempt.objects.filter(question__guide__school=school).delete()
            PracticeQuestion.objects.filter(guide__school=school).delete()
            StudyQuestion.objects.filter(guide__school=school).delete()
            TopicCheck.objects.filter(topic__guide__school=school).delete()
            GuideUpdate.objects.filter(guide__school=school).delete()
            LibraryFavorite.objects.filter(material__guide__school=school).delete()
            StudyMaterial.objects.filter(guide__school=school).delete()
            ExamTopic.objects.filter(guide__school=school).delete()
            ExamGuide.objects.filter(school=school).delete()

            AnalysisFeedback.objects.filter(analysis__school=school).delete()
            TextAnalysis.objects.filter(school=school).delete()
            QuestionResponse.objects.filter(question__evaluation__school=school).delete()
            QuestionSkill.objects.filter(question__evaluation__school=school).delete()
            Question.objects.filter(evaluation__school=school).delete()
            SkillEvidence.objects.filter(school=school).delete()
            SkillObservation.objects.filter(school=school).delete()
            SkillJudgment.objects.filter(school=school).delete()
            LearningIntervention.objects.filter(school=school).delete()
            LearningTrail.objects.filter(school=school).delete()
            LearningAlert.objects.filter(school=school).delete()
            InterventionStrategy.objects.filter(school=school).delete()
            ModelRun.objects.filter(school=school).delete()
            SkillRelation.objects.filter(school=school).delete()
            MasteryScale.objects.filter(school=school).delete()
            LearningEvidence.objects.filter(school=school).delete()

            GroupWorkRubricScore.objects.filter(group_work__school=school).delete()
            RubricScore.objects.filter(activity__school=school).delete()
            RubricDescriptor.objects.filter(criterion__rubric__school=school).delete()
            RubricLevel.objects.filter(rubric__school=school).delete()
            RubricCriterion.objects.filter(rubric__school=school).delete()
            Rubric.objects.filter(school=school).delete()
            LessonRecord.objects.filter(school=school).delete()
            LessonPlanReview.objects.filter(plan__school=school).delete()
            LessonPlan.objects.filter(school=school).delete()
            ActiveSearchAction.objects.filter(school=school).delete()

            MeetingFollowUp.objects.filter(meeting__school=school).delete()
            OfficeSlot.objects.filter(hours__school=school).delete()
            OfficeHours.objects.filter(school=school).delete()
            Meeting.objects.filter(school=school).delete()

            Reservation.objects.filter(school=school).delete()
            Loan.objects.filter(school=school).delete()
            Book.objects.filter(school=school).delete()
            LibrarySettings.objects.filter(school=school).delete()

            MedicationDose.objects.filter(request__school=school).delete()
            MedicationRequest.objects.filter(school=school).delete()
            HealthIncident.objects.filter(school=school).delete()
            PickupRecord.objects.filter(school=school).delete()
            DepartureNotice.objects.filter(school=school).delete()
            AuthorizedPickup.objects.filter(school=school).delete()
            EmergencyContact.objects.filter(student__school=school).delete()
            HealthRecord.objects.filter(school=school).delete()

            GateEvent.objects.filter(school=school).delete()
            StudentCard.objects.filter(school=school).delete()
            GateSettings.objects.filter(school=school).delete()

            Signup.objects.filter(workshop__school=school).delete()
            Workshop.objects.filter(school=school).delete()
            Claim.objects.filter(item__school=school).delete()
            FoundItem.objects.filter(school=school).delete()
            SupplyCheck.objects.filter(item__supply_list__school=school).delete()
            SupplyItem.objects.filter(supply_list__school=school).delete()
            SupplyList.objects.filter(school=school).delete()
            Booking.objects.filter(school=school).delete()
            Resource.objects.filter(school=school).delete()
            StudentDocument.objects.filter(document__school=school).delete()
            RequiredDocument.objects.filter(school=school).delete()

            MealMenu.objects.filter(school=school).delete()
            ClassSchedule.objects.filter(school=school).delete()
            CalendarPublication.objects.filter(school_year__school=school).delete()
            CalendarEvent.objects.filter(school=school).delete()
            CalendarPeriod.objects.filter(school=school).delete()

            SupportEvent.objects.filter(case__school=school).delete()
            SupportPlanReview.objects.filter(plan__case__school=school).delete()
            SupportPlanVersion.objects.filter(plan__case__school=school).delete()
            SupportPlan.objects.filter(case__school=school).delete()
            SupportNeed.objects.filter(case__school=school).delete()
            SupportRequest.objects.filter(case__school=school).delete()
            SupportDocument.objects.filter(case__school=school).delete()
            SupportCase.objects.filter(school=school).delete()
            SupportCategory.objects.filter(school=school).delete()
            SupportSettings.objects.filter(school=school).delete()

            Answer.objects.filter(campaign__school=school).delete()
            Campaign.objects.filter(school=school).delete()

            SchoolGoal.objects.filter(school=school).delete()
            CoordinationRecord.objects.filter(school=school).delete()

            PollVote.objects.filter(poll__school=school).delete()
            Poll.objects.filter(school=school).delete()
            AuthorizationResponse.objects.filter(authorization__school=school).delete()
            Authorization.objects.filter(school=school).delete()

            YearResult.objects.filter(school=school).delete()
            PriorGrade.objects.filter(record__school=school).delete()
            PriorYear.objects.filter(school=school).delete()

            # 1. Pedagógico que referencia turma, disciplina ou estudante.
            GroupWork.objects.filter(school=school).delete()
            Activity.objects.filter(school=school).delete()
            Submission.objects.filter(school=school).delete()
            Grade.objects.filter(school=school).delete()
            Evaluation.objects.filter(school=school).delete()
            AttendanceRecord.objects.filter(school=school).delete()
            AbsenceJustification.objects.filter(school=school).delete()
            Occurrence.objects.filter(school=school).delete()
            PedagogicalObservation.objects.filter(school=school).delete()
            InterventionPlan.objects.filter(school=school).delete()
            AcademicRule.objects.filter(school=school).delete()
            SchoolConfig.objects.filter(school=school).delete()

            # 2. Comunicação.
            Message.objects.filter(thread__school=school).delete()
            Thread.objects.filter(school=school).delete()
            Announcement.objects.filter(school=school).delete()
            ServiceRequest.objects.filter(school=school).delete()
            Notification.objects.filter(school=school).delete()

            # 3. Cadastro.
            GuardianLink.objects.filter(school=school).delete()
            GuardianProfile.objects.filter(user_id__in=contas).delete()
            Enrollment.objects.filter(school=school).delete()
            Student.objects.filter(pk__in=estudantes).delete()

            # 4. Acadêmico.
            TeacherAssignment.objects.filter(school=school).delete()
            ClassGroup.objects.filter(school=school).delete()
            Subject.objects.filter(school=school).delete()
            SchoolYear.objects.filter(school=school).delete()

            # 5. Contas e a escola. A auditoria sai antes porque aponta para
            # o usuário com SET_NULL e deixaria linhas sem dono.
            AuditLog.objects.filter(user_id__in=contas).delete()
            AuditLog.objects.filter(school=school).delete()
            User.objects.filter(pk__in=contas).delete()
            school.delete()

        restante = School.objects.filter(code=DEMO_CODE).count()
        self.stdout.write(
            self.style.SUCCESS("Escola de demonstração removida por completo.")
            if restante == 0
            else self.style.ERROR("A escola não saiu; verifique as dependências.")
        )

    # ----------------------------------------------------------------- criar
    def _criar(self, n_estudantes, semente):
        rnd = random.Random(semente)
        hoje = timezone.localdate()

        if School.objects.filter(code=DEMO_CODE).exists():
            self.stdout.write(
                self.style.WARNING(
                    "A escola de demonstração já existe. Rode com --limpar "
                    "antes para recriá-la."
                )
            )
            return

        with transaction.atomic():
            school = School.objects.create(
                name="Escola Demonstração (dados fictícios)", code=DEMO_CODE
            )
            SchoolConfig.objects.get_or_create(school=school)
            ano = SchoolYear.objects.create(
                school=school, name=str(hoje.year), is_current=True,
                start_date=hoje.replace(month=2, day=1),
                end_date=hoje.replace(month=12, day=15),
            )

            disciplinas = [
                Subject.objects.create(school=school, name=nome)
                for nome in DISCIPLINAS
            ]
            turmas = [
                ClassGroup.objects.create(
                    school=school, school_year=ano, name=nome, grade=serie, turn=turno
                )
                for nome, serie, turno in [
                    ("1º Ano A", "1º ano", "manha"),
                    ("1º Ano B", "1º ano", "manha"),
                    ("2º Ano A", "2º ano", "tarde"),
                    ("3º Ano A", "3º ano", "tarde"),
                ]
            ]

            equipe = {}
            for papel, usuario, nome, sobrenome in [
                (Role.DIRECAO, "demo.direcao", "Marta", "Rezende"),
                (Role.COORDENACAO, "demo.coordenacao", "Paulo", "Andrade"),
                (Role.SECRETARIA, "demo.secretaria", "Rita", "Camargo"),
            ]:
                equipe[papel] = self._user(
                    usuario, nome, sobrenome, papel, school
                )
            # Sem designação, o coordenador não alcança turma nenhuma (regra de
            # coordination.scope) e a demonstração mostrava telas vazias.
            from apps.coordination.models import CoordinatorAssignment

            CoordinatorAssignment.objects.create(
                school=school, coordinator=equipe[Role.COORDENACAO], all_school=True,
                starts_on=ano.start_date, created_by=equipe[Role.DIRECAO],
                area="Escola toda (demonstração)",
            )

            professores = []
            for i, (nome, sobrenome) in enumerate(
                [("Ana", "Pires"), ("Bruno", "Salles"), ("Carla", "Mendes"),
                 ("Diego", "Fontes")]
            ):
                prof = self._user(
                    f"demo.prof{i + 1}", nome, sobrenome, Role.PROFESSOR, school
                )
                professores.append(prof)

            # Cada professor cobre algumas disciplinas em todas as turmas.
            atribuicoes = []
            for idx, disc in enumerate(disciplinas):
                prof = professores[idx % len(professores)]
                for turma in turmas:
                    atribuicoes.append(
                        TeacherAssignment(
                            school=school, school_year=ano, teacher=prof,
                            class_group=turma, subject=disc,
                        )
                    )
            TeacherAssignment.objects.bulk_create(atribuicoes)

            # --- estudantes, matrículas e responsáveis ---
            estudantes = []
            for i in range(n_estudantes):
                nome = NOMES[i % len(NOMES)]
                # A cada volta pelos nomes, o sobrenome é deslocado 5 posições.
                # Antes o deslocamento era 1 e, como 35 + 1 = 36 é múltiplo de
                # 18, a segunda volta repetia nome E sobrenome da primeira
                # (três "Alice Almeida" na escola). Assim, os nomes completos
                # só se repetem a partir de 315 estudantes.
                sobrenome = SOBRENOMES[(i + 5 * (i // len(NOMES))) % len(SOBRENOMES)]
                st = Student.objects.create(
                    school=school,
                    first_name=nome,
                    last_name=sobrenome,
                    birth_date=hoje - timedelta(days=rnd.randint(2200, 3600)),
                    status="ativo",
                )
                turma = turmas[i % len(turmas)]
                Enrollment.objects.create(
                    school=school, student=st, class_group=turma, school_year=ano,
                    enrollment_number=f"{hoje.year}{i + 1:04d}", status="ativo",
                    started_on=ano.start_date,
                )
                estudantes.append(st)

            # Um responsável por família; a cada 6 estudantes, um responsável
            # com dois filhos, para exercitar a troca entre eles.
            responsaveis = []
            i = 0
            while i < len(estudantes):
                filhos = estudantes[i : i + (2 if i % 6 == 0 else 1)]
                idx = len(responsaveis) + 1
                resp = self._user(
                    f"demo.resp{idx}",
                    rnd.choice(NOMES),
                    filhos[0].last_name,
                    Role.RESPONSAVEL,
                    school,
                )
                GuardianProfile.objects.get_or_create(
                    user=resp,
                    defaults={"relation": rnd.choice(["mae", "pai", "avo"])},
                )
                for filho in filhos:
                    GuardianLink.objects.create(
                        school=school, guardian=resp, student=filho,
                        status="aprovado", relation="mae",
                        validated_by=equipe[Role.SECRETARIA],
                        validated_at=timezone.now(),
                    )
                responsaveis.append(resp)
                i += len(filhos)

            # Alguns vínculos pendentes, para a secretaria ter fila de trabalho.
            for st in estudantes[:3]:
                pend = self._user(
                    f"demo.pendente{st.pk}", rnd.choice(NOMES), st.last_name,
                    Role.RESPONSAVEL, school,
                )
                GuardianLink.objects.create(
                    school=school, guardian=pend, student=st, status="pendente",
                    relation="outro", requested_by=pend,
                )

            # --- atividades de casa ---
            atividades = []
            for turma in turmas:
                profs_turma = {
                    a.subject_id: a.teacher
                    for a in TeacherAssignment.objects.filter(class_group=turma)
                }
                for k in range(9):
                    disc = disciplinas[k % len(disciplinas)]
                    titulo, instr = TAREFAS[k % len(TAREFAS)]
                    publicada = hoje - timedelta(days=rnd.randint(1, 45))
                    if k == 0:
                        status, prazo = Activity.Status.DRAFT, None
                    elif k == 1:
                        status = Activity.Status.CANCELED
                        prazo = publicada + timedelta(days=7)
                    else:
                        status = Activity.Status.PUBLISHED
                        prazo = publicada + timedelta(days=rnd.choice([2, 5, 9, 14, -3]))
                    atividades.append(
                        Activity(
                            school=school, class_group=turma, subject=disc,
                            title=f"{titulo} — {turma.name}",
                            description=instr,
                            materials="Caderno, lápis e borracha.",
                            criteria="Capricho, organização e tentativa registrada.",
                            published_date=publicada,
                            deadline=prazo,
                            class_date=publicada,
                            status=status,
                            cancel_reason=(
                                "Aula remarcada; conteúdo volta na próxima semana."
                                if status == Activity.Status.CANCELED
                                else ""
                            ),
                            created_by=profs_turma.get(disc.pk, professores[0]),
                        )
                    )
            Activity.objects.bulk_create(atividades)
            # Dados de demonstração nascem como "já avisados": sem isto, a
            # primeira página aberta dispararia avisos de tudo ao mesmo tempo.
            Activity.objects.filter(school=school).exclude(
                status=Activity.Status.DRAFT
            ).update(notified_at=timezone.now())

            # Entregas de parte das atividades publicadas.
            entregas = []
            publicadas = Activity.objects.filter(
                school=school, status=Activity.Status.PUBLISHED
            ).select_related("class_group")
            for act in publicadas:
                matriculados = [
                    e.student
                    for e in Enrollment.objects.filter(
                        class_group=act.class_group, status="ativo"
                    ).select_related("student")
                ]
                for st in matriculados:
                    if rnd.random() < 0.65:
                        entregue = rnd.random() < 0.8
                        entregas.append(
                            Submission(
                                school=school, activity=act, student=st,
                                status="entregue" if entregue else "nao_entregue",
                                grade=(
                                    round(rnd.uniform(5, 10), 2) if entregue else None
                                ),
                                comment="" if entregue else "Não trouxe o caderno.",
                                updated_by=act.created_by,
                            )
                        )
            Submission.objects.bulk_create(entregas)

            # --- trabalhos em grupo ---
            for turma in turmas:
                matriculados = [
                    e.student
                    for e in Enrollment.objects.filter(
                        class_group=turma, status="ativo"
                    ).select_related("student")
                ]
                profs_turma = {
                    a.subject_id: a.teacher
                    for a in TeacherAssignment.objects.filter(class_group=turma)
                }
                for k, (titulo, enunciado, apresentacao) in enumerate(TRABALHOS):
                    disc = disciplinas[k % len(disciplinas)]
                    publicado = hoje - timedelta(days=rnd.randint(2, 40))
                    if k == 0:
                        status, prazo = GroupWork.Status.DRAFT, None
                    elif k == 1:
                        status = GroupWork.Status.CANCELED
                        prazo = publicado + timedelta(days=10)
                    else:
                        status = GroupWork.Status.PUBLISHED
                        prazo = publicado + timedelta(
                            days=rnd.choice([2, 8, 15, 21, -4])
                        )
                    work = GroupWork.objects.create(
                        school=school,
                        class_group=turma,
                        subject=disc,
                        title=f"{titulo} — {turma.name}",
                        description=enunciado,
                        objectives=(
                            "Trabalhar pesquisa, organização da informação e "
                            "apresentação em equipe."
                        ),
                        guidelines="Participação de todos, clareza e fontes citadas.",
                        materials="Cartolina, cola, tesoura sem ponta e revistas.",
                        presentation=apresentacao,
                        published_date=publicado,
                        deadline=prazo,
                        delivery_mode=(
                            GroupWork.DeliveryMode.INDIVIDUAL
                            if k % 3 == 2
                            else GroupWork.DeliveryMode.GROUP
                        ),
                        status=status,
                        cancel_reason=(
                            "Apresentação remarcada para o próximo bimestre."
                            if status == GroupWork.Status.CANCELED
                            else ""
                        ),
                        created_by=profs_turma.get(disc.pk, professores[0]),
                        notified_at=(
                            None if status == GroupWork.Status.DRAFT else timezone.now()
                        ),
                    )
                    if not matriculados:
                        continue
                    # Grupos de 3 a 4 integrantes, como numa turma real.
                    sorteados = list(matriculados)
                    rnd.shuffle(sorteados)
                    tamanho = rnd.choice([3, 4])
                    for i in range(0, len(sorteados), tamanho):
                        fatia = sorteados[i : i + tamanho]
                        if not fatia:
                            continue
                        g = WorkGroup.objects.create(
                            group_work=work, name=f"Grupo {i // tamanho + 1}"
                        )
                        WorkGroupMember.objects.bulk_create(
                            WorkGroupMember(
                                group=g, student=st, added_by=work.created_by
                            )
                            for st in fatia
                        )
                    # Registra entrega de parte dos grupos publicados.
                    if status == GroupWork.Status.PUBLISHED and rnd.random() < 0.6:
                        for g in work.groups.all():
                            membros = [m.student for m in g.active_members()]
                            if work.delivery_mode == GroupWork.DeliveryMode.GROUP:
                                alvos = [None]
                            else:
                                alvos = membros
                            for alvo in alvos:
                                if rnd.random() < 0.75:
                                    GroupWorkDelivery.objects.create(
                                        group_work=work,
                                        group=g,
                                        student=alvo,
                                        status=rnd.choice(
                                            ["entregue", "entregue", "atrasado"]
                                        ),
                                        grade=round(rnd.uniform(6, 10), 2),
                                        delivered_at=prazo or publicado,
                                        registered_by=work.created_by,
                                    )

            # --- avaliações e notas ---
            notas = []
            for turma in turmas:
                for disc in disciplinas[:4]:
                    prof = TeacherAssignment.objects.filter(
                        class_group=turma, subject=disc
                    ).first().teacher
                    for bim in (1, 2):
                        ev = Evaluation.objects.create(
                            school=school, subject=disc, class_group=turma,
                            title=f"Avaliação {bim}º bimestre — {disc.name}",
                            description="Avaliação escrita.",
                            weight=1,
                            date=hoje - timedelta(days=90 - bim * 35),
                            status=Evaluation.Status.PUBLISHED,
                            created_by=prof,
                        )
                        for e in Enrollment.objects.filter(
                            class_group=turma, status="ativo"
                        ).select_related("student"):
                            notas.append(
                                Grade(
                                    school=school, evaluation=ev, student=e.student,
                                    value=round(rnd.uniform(3.5, 10), 2),
                                    updated_by=prof,
                                )
                            )
            Grade.objects.bulk_create(notas)

            # --- frequência dos últimos 30 dias letivos ---
            registros = []
            for turma in turmas:
                alunos = [
                    e.student
                    for e in Enrollment.objects.filter(
                        class_group=turma, status="ativo"
                    ).select_related("student")
                ]
                prof = TeacherAssignment.objects.filter(class_group=turma).first().teacher
                dia = hoje
                contados = 0
                while contados < 30:
                    dia -= timedelta(days=1)
                    if dia.weekday() >= 5:
                        continue
                    contados += 1
                    for st in alunos:
                        r = rnd.random()
                        status = "presente" if r < 0.88 else ("atraso" if r < 0.94 else "falta")
                        registros.append(
                            AttendanceRecord(
                                school=school, class_group=turma, student=st,
                                date=dia, status=status, recorded_by=prof,
                            )
                        )
            AttendanceRecord.objects.bulk_create(registros, batch_size=2000)

            # --- registros pedagógicos, para os painéis terem conteúdo ---
            for st in estudantes[:10]:
                Occurrence.objects.create(
                    school=school, student=st,
                    recorded_by=equipe[Role.COORDENACAO],
                    date=hoje - timedelta(days=rnd.randint(5, 40)),
                    description="Conversa sobre organização do material.",
                    providencias="Combinado acompanhamento semanal com a família.",
                    status=rnd.choice(["aberta", "em_acompanhamento", "concluida"]),
                )
            for st in estudantes[:14]:
                PedagogicalObservation.objects.create(
                    school=school, student=st, teacher=professores[0],
                    subject=disciplinas[0],
                    content="Operações com fração",
                    dificuldades="Confunde numerador e denominador ao somar.",
                    habilidades="Lê e interpreta o enunciado com autonomia.",
                    estrategias="Material concreto e exercícios em dupla.",
                    observed_at=hoje - timedelta(days=rnd.randint(3, 30)),
                )

            # Módulos complementares: preenche todas as outras abas da
            # plataforma (comunicação, calendário, saúde, biblioteca...).
            self._seed_extras(school, ano, hoje, rnd, disciplinas, turmas,
                              estudantes, professores, equipe, responsaveis)

        # Fora da transação principal: recalcula as evidências por habilidade e
        # os alertas do EIA-Cognitio a partir do que acabou de ser semeado.
        self._rebuild_cognitio(school)
        self._resumo(school, n_estudantes)

    # ----------------------------------------------- módulos complementares
    def _aware(self, d, t):
        return timezone.make_aware(datetime.combine(d, t))

    def _alunos(self, turma):
        return [e.student for e in Enrollment.objects.filter(
            class_group=turma, status="ativo").select_related("student")]

    def _teacher_for(self, turma, subject, professores):
        a = TeacherAssignment.objects.filter(class_group=turma, subject=subject).first()
        return a.teacher if a else professores[0]

    def _seed_extras(self, school, ano, hoje, rnd, disciplinas, turmas,
                     estudantes, professores, equipe, responsaveis):
        """Preenche todas as outras abas da plataforma com dados fictícios."""
        self._seed_academic_rules(school, disciplinas)
        self._seed_calendar(school, ano, equipe, hoje)
        self._seed_rotina(school, turmas, disciplinas, professores, equipe, hoje)
        self._seed_coordination(school, turmas, professores, equipe, hoje)
        self._seed_supplies(school, ano, turmas, equipe, estudantes, hoje, rnd)
        self._seed_booking(school, turmas, professores, equipe, hoje)
        self._seed_library(school, estudantes, equipe, professores, hoje, rnd)
        self._seed_care(school, estudantes, equipe, responsaveis, hoje, rnd)
        self._seed_paperwork(school, estudantes, equipe, hoje, rnd)
        self._seed_gate(school, turmas, estudantes, equipe, hoje, rnd)
        self._seed_workshops(school, turmas, estudantes, equipe, hoje, rnd)
        self._seed_lostfound(school, estudantes, equipe, responsaveis, hoje, rnd)
        self._seed_communication(school, ano, turmas, estudantes, equipe,
                                 professores, responsaveis, hoje, rnd)
        self._seed_meetings(school, turmas, estudantes, equipe, professores,
                            responsaveis, hoje, rnd)
        self._seed_inclusion(school, estudantes, equipe, professores, disciplinas, hoje)
        self._seed_analytics(school, turmas, equipe, hoje)
        self._seed_reenroll(school, ano, turmas, equipe, estudantes, hoje, rnd)
        self._seed_longitudinal(school, estudantes, ano, turmas, equipe, hoje, rnd)
        self._seed_pedagogy_extras(school, turmas, disciplinas, estudantes,
                                   professores, equipe, responsaveis, hoje, rnd)
        self._seed_study(school, turmas, disciplinas, estudantes, professores, hoje, rnd)
        self._seed_cognitio(school, turmas, disciplinas, estudantes, professores, hoje, rnd)

    # -------- acadêmico (regras de média por disciplina)
    def _seed_academic_rules(self, school, disciplinas):
        from apps.pedagogy.models import AcademicRule

        formulas = [AcademicRule.Formula.ARITHMETIC, AcademicRule.Formula.WEIGHTED,
                    AcademicRule.Formula.ARITHMETIC, AcademicRule.Formula.BEST]
        for i, disc in enumerate(disciplinas):
            AcademicRule.objects.get_or_create(
                school=school, subject=disc,
                defaults={"formula": formulas[i % len(formulas)],
                          "passing_grade": Decimal("6.00")},
            )

    # -------- calendário escolar
    def _seed_calendar(self, school, ano, equipe, hoje):
        from apps.school_calendar.models import (
            CalendarEvent, CalendarPeriod, CalendarPublication)

        y = hoje.year
        import datetime as _dt
        bimestres = [
            ("1º bimestre", _dt.date(y, 2, 1), _dt.date(y, 4, 15)),
            ("2º bimestre", _dt.date(y, 4, 16), _dt.date(y, 6, 30)),
            ("3º bimestre", _dt.date(y, 8, 1), _dt.date(y, 9, 30)),
            ("4º bimestre", _dt.date(y, 10, 1), _dt.date(y, 12, 15)),
        ]
        for nome, ini, fim in bimestres:
            CalendarPeriod.objects.create(
                school=school, school_year=ano, kind=CalendarPeriod.Kind.BIMESTRE,
                name=nome, start=ini, end=fim)

        E = CalendarEvent
        eventos = [
            (E.Kind.CLASSES_START, "Início das aulas", _dt.date(y, 2, 1), None, False, E.Audience.ALL),
            (E.Kind.HOLIDAY, "Tiradentes", _dt.date(y, 4, 21), None, True, E.Audience.ALL),
            (E.Kind.VACATION, "Recesso escolar de julho", _dt.date(y, 7, 1), _dt.date(y, 7, 15), True, E.Audience.ALL),
            (E.Kind.HOLIDAY, "Independência do Brasil", _dt.date(y, 9, 7), None, True, E.Audience.ALL),
            (E.Kind.MEETING, "Reunião pedagógica", _dt.date(y, 8, 4), None, True, E.Audience.STAFF),
            (E.Kind.COUNCIL, "Conselho de classe do 3º bimestre", _dt.date(y, 10, 3), None, True, E.Audience.STAFF),
            (E.Kind.EVENT, "Festa da família", _dt.date(y, 5, 24), None, False, E.Audience.ALL),
        ]
        for kind, titulo, ini, fim, sem_aula, aud in eventos:
            CalendarEvent.objects.create(
                school=school, school_year=ano, kind=kind, title=titulo, start=ini,
                end=fim, no_classes=sem_aula, audience=aud,
                description="Evento de demonstração.", created_by=equipe[Role.DIRECAO])
        CalendarPublication.objects.create(
            school_year=ano, published_by=equipe[Role.DIRECAO])

    # -------- rotina: cardápio e quadro de horários
    def _seed_rotina(self, school, turmas, disciplinas, professores, equipe, hoje):
        from apps.rotina.models import ClassSchedule, MealMenu

        pratos = [
            ("Pão com queijo e suco de laranja", "Pão francês, queijo, laranja", "glúten, leite"),
            ("Arroz, feijão, frango grelhado e salada", "Arroz, feijão, frango, alface, tomate", ""),
            ("Bolo de cenoura e leite", "Cenoura, farinha, ovo, leite", "glúten, ovo, leite"),
            ("Macarrão ao molho de tomate", "Macarrão, tomate, cebola", "glúten"),
            ("Fruta da estação e biscoito", "Banana, biscoito", "glúten"),
        ]
        refeicoes = [MealMenu.Meal.MORNING, MealMenu.Meal.LUNCH, MealMenu.Meal.AFTERNOON]
        dia = hoje
        contados = 0
        idx = 0
        while contados < 5:
            if dia.weekday() < 5:
                for r in refeicoes:
                    desc, ing, alg = pratos[idx % len(pratos)]
                    idx += 1
                    MealMenu.objects.create(
                        school=school, date=dia, meal=r, description=desc,
                        ingredients=ing, allergens=alg,
                        validated_by="Nutricionista Clara Nogueira (CRN 1-12345)",
                        substitution=("Opção sem lactose para quem tem restrição."
                                      if "leite" in alg else ""),
                        changed=(contados == 0 and r == MealMenu.Meal.LUNCH),
                        change_note=("Troca de última hora: faltou o ingrediente principal."
                                     if (contados == 0 and r == MealMenu.Meal.LUNCH) else ""),
                        updated_by=equipe[Role.SECRETARIA])
                contados += 1
            dia += timedelta(days=1)

        horas = [(time(7, 30), time(8, 20)), (time(8, 20), time(9, 10)),
                 (time(9, 30), time(10, 20)), (time(10, 20), time(11, 10))]
        for turma in turmas:
            for weekday in range(5):
                for s, (ini, fim) in enumerate(horas):
                    disc = disciplinas[(weekday + s) % len(disciplinas)]
                    ClassSchedule.objects.create(
                        school=school, class_group=turma, weekday=weekday,
                        start_time=ini, end_time=fim, subject=disc,
                        teacher=self._teacher_for(turma, disc, professores),
                        room=f"Sala {turma.name[:1]}{s + 1}")

    # -------- coordenação (registros)
    def _seed_coordination(self, school, turmas, professores, equipe, hoje):
        from apps.coordination.models import CoordinationRecord

        K = CoordinationRecord.Kind
        dados = [
            (K.GUIDANCE, "Orientação sobre devolutivas formativas", professores[0], turmas[0]),
            (K.PLANNING, "Acompanhamento do planejamento do bimestre", professores[1], turmas[1]),
            (K.FOLLOW_UP, "Acompanhamento da turma com baixa frequência", None, turmas[2]),
            (K.MEETING, "Reunião de alinhamento dos anos iniciais", None, None),
        ]
        for i, (kind, titulo, prof, turma) in enumerate(dados):
            CoordinationRecord.objects.create(
                school=school, kind=kind, date=hoje - timedelta(days=i * 4 + 2),
                title=titulo, notes="Registro interno de demonstração da coordenação.",
                teacher=prof, class_group=turma,
                participants="Coordenação e equipe pedagógica",
                created_by=equipe[Role.COORDENACAO])

    # -------- materiais escolares
    def _seed_supplies(self, school, ano, turmas, equipe, estudantes, hoje, rnd):
        from apps.supplies.models import SupplyCheck, SupplyItem, SupplyList

        itens = ["Caderno brochura 96 folhas", "Lápis preto nº 2", "Borracha branca",
                 "Apontador com depósito", "Caixa de lápis de cor (12 cores)",
                 "Cola branca 90g", "Tesoura sem ponta", "Régua de 30 cm",
                 "Pasta com elástico", "Tubo de tinta guache"]
        for i, turma in enumerate(turmas[:3]):
            publicada = i == 0
            lista = SupplyList.objects.create(
                school=school, school_year=ano, title=f"Lista de materiais — {turma.grade}",
                grade=turma.grade,
                intro="Identifique tudo com o nome. O material em bom estado pode ser reaproveitado.",
                deliver_by=hoje + timedelta(days=20),
                status=(SupplyList.Status.PUBLISHED if publicada else
                        (SupplyList.Status.REVIEW if i == 1 else SupplyList.Status.DRAFT)),
                revision=1 if publicada else 0,
                created_by=equipe[Role.COORDENACAO],
                published_by=equipe[Role.DIRECAO] if publicada else None,
                published_at=timezone.now() if publicada else None)
            lista.class_groups.add(turma)
            criados = []
            for pos, nome in enumerate(itens[: 6 + i]):
                criados.append(SupplyItem.objects.create(
                    supply_list=lista, name=nome,
                    quantity=rnd.choice([1, 1, 2, 3]), position=pos,
                    optional=(pos == len(itens[: 6 + i]) - 1)))
            if publicada:
                for st in self._alunos(turma)[:6]:
                    SupplyCheck.objects.create(
                        item=rnd.choice(criados), student=st,
                        checked_by=equipe[Role.SECRETARIA])

    # -------- reserva de espaços e equipamentos
    def _seed_booking(self, school, turmas, professores, equipe, hoje):
        from apps.booking.models import Booking, Resource

        R = Resource.Kind
        recursos = [
            Resource.objects.create(school=school, name="Sala de informática", kind=R.SPACE,
                                    notes="20 computadores."),
            Resource.objects.create(school=school, name="Quadra poliesportiva", kind=R.SPACE),
            Resource.objects.create(school=school, name="Laboratório de ciências", kind=R.SPACE),
            Resource.objects.create(school=school, name="Projetor 1", kind=R.EQUIPMENT),
            Resource.objects.create(school=school, name="Projetor 2", kind=R.EQUIPMENT),
        ]
        dia = hoje + timedelta(days=1)
        horarios = [(time(8, 0), time(9, 0)), (time(9, 0), time(10, 0)),
                    (time(10, 0), time(11, 0)), (time(14, 0), time(15, 0))]
        for i, rec in enumerate(recursos):
            while dia.weekday() >= 5:
                dia += timedelta(days=1)
            ini, fim = horarios[i % len(horarios)]
            Booking.objects.create(
                school=school, resource=rec, day=dia, start=ini, end=fim,
                class_group=turmas[i % len(turmas)], purpose="Aula de demonstração",
                booked_by=professores[i % len(professores)])
            dia += timedelta(days=1)
        # Uma reserva cancelada, para mostrar o histórico.
        Booking.objects.create(
            school=school, resource=recursos[1], day=hoje + timedelta(days=3),
            start=time(10, 0), end=time(11, 0), class_group=turmas[0],
            purpose="Ensaio da apresentação (cancelado)",
            booked_by=professores[0], canceled_at=timezone.now(),
            canceled_by=professores[0])

    # -------- biblioteca
    def _seed_library(self, school, estudantes, equipe, professores, hoje, rnd):
        from apps.library.models import Book, LibrarySettings, Loan, Reservation

        s = LibrarySettings.objects.create(school=school, loan_days=14, max_loans=2)
        s.librarians.add(professores[0])
        C = Book.Category
        acervo = [
            ("O menino maluquinho", "Ziraldo", C.CHILDREN), ("Marcelo, marmelo, martelo", "Ruth Rocha", C.CHILDREN),
            ("A bolsa amarela", "Lygia Bojunga", C.YOUTH), ("Reinações de Narizinho", "Monteiro Lobato", C.CHILDREN),
            ("O pequeno príncipe", "Antoine de Saint-Exupéry", C.FICTION), ("Turma da Mônica", "Mauricio de Sousa", C.COMICS),
            ("Poemas para crianças", "Cecília Meireles", C.POETRY), ("O universo em pequenos passos", "VV.AA.", C.NONFICTION),
            ("Atlas geográfico escolar", "IBGE", C.REFERENCE), ("Contos de fada", "Irmãos Grimm", C.CHILDREN),
            ("A arca de Noé", "Vinicius de Moraes", C.POETRY), ("Dicionário ilustrado", "Aurélio", C.REFERENCE),
            ("Menina bonita do laço de fita", "Ana Maria Machado", C.CHILDREN), ("O gato de botas", "Charles Perrault", C.CHILDREN),
            ("Ciências divertidas", "VV.AA.", C.NONFICTION), ("História do Brasil para crianças", "VV.AA.", C.NONFICTION),
        ]
        livros = [Book.objects.create(
            school=school, title=t, author=a, category=c,
            copies=rnd.choice([1, 2, 2, 3]), location=f"Estante {chr(65 + i % 5)}",
            created_by=equipe[Role.SECRETARIA]) for i, (t, a, c) in enumerate(acervo)]

        alunos = estudantes[:14]
        for i, st in enumerate(alunos):
            livro = livros[i % len(livros)]
            if i < 6:  # devolvidos
                Loan.objects.create(
                    school=school, book=livro, student=st,
                    lent_at=self._aware(hoje - timedelta(days=30 - i), time(9, 0)),
                    due_on=hoje - timedelta(days=16 - i),
                    returned_at=self._aware(hoje - timedelta(days=18 - i), time(9, 0)),
                    condition_note="Devolvido em bom estado",
                    lent_by=equipe[Role.SECRETARIA], returned_by=equipe[Role.SECRETARIA])
            elif i == 6:  # atrasado
                Loan.objects.create(
                    school=school, book=livro, student=st,
                    lent_at=self._aware(hoje - timedelta(days=20), time(9, 0)),
                    due_on=hoje - timedelta(days=6), lent_by=equipe[Role.SECRETARIA])
            else:  # em dia
                Loan.objects.create(
                    school=school, book=livro, student=st,
                    lent_at=self._aware(hoje - timedelta(days=3), time(9, 0)),
                    due_on=hoje + timedelta(days=11), lent_by=equipe[Role.SECRETARIA])
        # Fila de reserva de um livro muito pedido.
        Reservation.objects.create(school=school, book=livros[0], student=estudantes[20],
                                   status=Reservation.Status.WAITING,
                                   created_by=equipe[Role.SECRETARIA])
        Reservation.objects.create(school=school, book=livros[4], student=estudantes[21],
                                   status=Reservation.Status.READY, ready_on=hoje,
                                   expires_on=hoje + timedelta(days=3),
                                   created_by=equipe[Role.SECRETARIA])

    # -------- saúde e emergência
    def _seed_care(self, school, estudantes, equipe, responsaveis, hoje, rnd):
        from apps.care.models import (
            AuthorizedPickup, DepartureNotice, EmergencyContact, HealthIncident,
            HealthRecord, MedicationDose, MedicationRequest, PickupRecord)

        D = HealthRecord.Diet
        perfis = [
            ("Alergia a amendoim e a frutos do mar (reação com inchaço).", D.NONE, "Asma leve."),
            ("", D.LACTOSE, ""), ("", D.GLUTEN, "Doença celíaca."),
            ("Alergia a picada de abelha.", D.NONE, ""), ("", D.VEGETARIAN, ""),
            ("", D.NONE, "Diabetes tipo 1 — ver plano de crise."),
        ]
        alunos = estudantes[:14]
        for i, st in enumerate(alunos):
            alerg, diet, cond = perfis[i % len(perfis)]
            HealthRecord.objects.create(
                school=school, student=st, allergies=alerg, diet=diet,
                conditions=cond,
                crisis_plan=("Afastar da causa, manter em observação e avisar a família."
                             if (alerg or cond) else ""),
                emergency_transport=True,
                consent_at=timezone.now(), consent_by=equipe[Role.SECRETARIA],
                updated_by=equipe[Role.SECRETARIA])
            EmergencyContact.objects.create(student=st, name=f"Responsável de {st.first_name}",
                                            relationship="mãe", phone="(61) 90000-0000", order=1)
            EmergencyContact.objects.create(student=st, name="Avó materna",
                                            relationship="avó", phone="(61) 90000-1111", order=2)
        for st in estudantes[:10]:
            AuthorizedPickup.objects.create(
                school=school, student=st, name="Tio responsável",
                relationship="tio", document_hint="RG final 4821",
                phone="(61) 90000-2222", created_by=equipe[Role.SECRETARIA])
        for i, st in enumerate(estudantes[:3]):
            DepartureNotice.objects.create(
                school=school, student=st, day=hoje + timedelta(days=1),
                time=time(15, 0), guardian_pickup=True,
                reason="Consulta médica", created_by=responsaveis[i % len(responsaveis)])
        for st in estudantes[3:6]:
            PickupRecord.objects.create(
                school=school, student=st, at=self._aware(hoje - timedelta(days=1), time(17, 0)),
                kind=PickupRecord.Kind.GUARDIAN, person_name="Mãe (responsável)",
                recorded_by=equipe[Role.SECRETARIA])
        K, O = HealthIncident.Kind, HealthIncident.Outcome
        casos = [
            (K.FEVER, O.PICKUP, False), (K.INJURY, O.BACK, True),
            (K.UNWELL, O.WATCH, False), (K.ALLERGY, O.HOSPITAL, False),
            (K.CRISIS, O.PICKUP, False),
        ]
        for i, (kind, outcome, cabeca) in enumerate(casos):
            inc = HealthIncident.objects.create(
                school=school, student=estudantes[i], happened_at=self._aware(
                    hoje - timedelta(days=i + 1), time(10, 30)),
                kind=kind, place=rnd.choice(["pátio", "quadra", "sala 3"]),
                description="Situação de demonstração atendida pela escola.",
                head_hit=cabeca,
                care_given="Repouso na secretaria e conferência da ficha de saúde.",
                phone_contact="Mãe, por telefone, às 10h40.", outcome=outcome,
                registered_by=equipe[Role.SECRETARIA])
            if outcome in HealthIncident.URGENT:
                inc.acknowledged_by = responsaveis[i % len(responsaveis)]
                inc.acknowledged_at = timezone.now()
                inc.family_note = "Ciente, obrigada pelo cuidado."
                inc.save()
        # Medicação: um pedido autorizado com doses, um aguardando.
        med = MedicationRequest.objects.create(
            school=school, student=estudantes[0], medicine="Amoxicilina 250 mg/5 ml",
            dose="5 ml", times="10:00", start_date=hoje - timedelta(days=4),
            end_date=hoje + timedelta(days=3), reason="Infecção de garganta",
            instructions="Depois do lanche; agitar antes.",
            prescriber="Dra. Helena Martins (CRM 12345)", prescription_date=hoje - timedelta(days=5),
            requested_by=responsaveis[0], status=MedicationRequest.Status.APPROVED,
            reviewed_by=equipe[Role.SECRETARIA], reviewed_at=timezone.now(),
            review_note="Receita conferida.")
        dia = hoje - timedelta(days=4)
        while dia <= hoje:
            if dia.weekday() < 5:
                MedicationDose.objects.create(
                    request=med, day=dia, slot="10:00",
                    result=rnd.choice([MedicationDose.Result.GIVEN, MedicationDose.Result.GIVEN,
                                       MedicationDose.Result.ABSENT]),
                    given_by=equipe[Role.SECRETARIA])
            dia += timedelta(days=1)
        MedicationRequest.objects.create(
            school=school, student=estudantes[1], medicine="Dipirona 500 mg/ml",
            dose="15 gotas", times="11:00", start_date=hoje,
            end_date=hoje + timedelta(days=2), reason="Dor",
            prescriber="Dra. Helena Martins (CRM 12345)", prescription_date=hoje - timedelta(days=1),
            requested_by=responsaveis[1 % len(responsaveis)],
            status=MedicationRequest.Status.PENDING)

    # -------- documentos da matrícula (papelada)
    def _seed_paperwork(self, school, estudantes, equipe, hoje, rnd):
        from apps.paperwork.models import RequiredDocument, StudentDocument

        docs = [RequiredDocument.objects.create(
            school=school, name=nome, hint=hint, mandatory=obrig, position=i)
            for i, (nome, obrig, hint) in enumerate(RequiredDocument.DEFAULTS)]
        for st in estudantes[:40]:
            # A maioria entregou os obrigatórios; alguns ficam pendentes.
            for d in docs[:5]:
                if rnd.random() < 0.85:
                    StudentDocument.objects.create(
                        student=st, document=d, status=StudentDocument.Status.DELIVERED,
                        on=hoje - timedelta(days=rnd.randint(10, 60)),
                        registered_by=equipe[Role.SECRETARIA])

    # -------- portaria: carteirinhas e entradas/saídas
    def _seed_gate(self, school, turmas, estudantes, equipe, hoje, rnd):
        from apps.gate.models import GateEvent, GateSettings, StudentCard
        from apps.gate.services import new_code

        GateSettings.objects.create(school=school, updated_by=equipe[Role.DIRECAO])
        validade = hoje.replace(month=12, day=31)
        cards = {}
        for st in estudantes:
            cards[st.pk] = StudentCard.objects.create(
                school=school, student=st, code=new_code(),
                issued_by=equipe[Role.SECRETARIA], valid_until=validade)
        turma_de = {}
        for turma in turmas:
            for st in self._alunos(turma):
                turma_de[st.pk] = turma
        entrada = {"manha": time(7, 30), "tarde": time(13, 0)}
        for st in estudantes[:40]:
            turma = turma_de.get(st.pk, turmas[0])
            hora_turno = entrada.get(turma.turn, time(7, 30))
            atraso = rnd.random() < 0.15
            at = self._aware(hoje, hora_turno) + timedelta(minutes=20 if atraso else -5)
            GateEvent.objects.create(
                school=school, student=st, card=cards[st.pk], class_group=turma,
                kind=GateEvent.Kind.ENTRY, method=GateEvent.Method.QR, day=hoje, at=at,
                expected=hora_turno, late=atraso, minutes_late=20 if atraso else None,
                recorded_by=equipe[Role.SECRETARIA])

    # -------- oficinas e projetos
    def _seed_workshops(self, school, turmas, estudantes, equipe, hoje, rnd):
        from apps.workshops.models import Signup, Workshop

        dados = [
            ("Oficina de robótica", "Montagem de robôs simples com sucata.", "terças, 14h às 15h30", 2),
            ("Coral da escola", "Ensaios e apresentações.", "quartas, 10h às 11h", 3),
            ("Clube de xadrez", "Do básico ao primeiro torneio.", "sextas, 14h às 15h", 2),
        ]
        for titulo, desc, horario, vagas in dados:
            w = Workshop.objects.create(
                school=school, title=titulo, description=desc, schedule=horario,
                place="Sala multiuso", starts_on=hoje + timedelta(days=7),
                ends_on=hoje + timedelta(days=120), capacity=vagas,
                signup_until=hoje + timedelta(days=5), organizer=equipe[Role.COORDENACAO],
                published_at=timezone.now())
            candidatos = rnd.sample(estudantes, min(vagas + 2, len(estudantes)))
            for n, st in enumerate(candidatos):
                confirmado = n < vagas
                Signup.objects.create(
                    workshop=w, student=st,
                    status=(Signup.Status.CONFIRMED if confirmado else Signup.Status.WAITING),
                    queued_at=self._aware(hoje - timedelta(days=1), time(9, n % 59)),
                    signed_by=equipe[Role.SECRETARIA])

    # -------- achados e perdidos
    def _seed_lostfound(self, school, estudantes, equipe, responsaveis, hoje, rnd):
        from apps.lostfound.models import Claim, FoundItem

        C = FoundItem.Category
        itens = [
            ("Casaco azul-marinho tamanho 10", C.CLOTHES, "quadra", FoundItem.Status.KEPT),
            ("Garrafa rosa com adesivos", C.BOTTLE, "pátio", FoundItem.Status.KEPT),
            ("Estojo cinza com lápis", C.SUPPLIES, "sala 3", FoundItem.Status.KEPT),
            ("Óculos de grau infantil", C.GLASSES, "biblioteca", FoundItem.Status.RETURNED),
            ("Celular (guardado na secretaria)", C.ELECTRONIC, "refeitório", FoundItem.Status.KEPT),
            ("Casaco cinza velho", C.CLOTHES, "pátio", FoundItem.Status.DONATED),
        ]
        criados = []
        for titulo, cat, local, status in itens:
            it = FoundItem.objects.create(
                school=school, title=titulo, category=cat,
                details="" if cat in FoundItem.VALUABLE else "Sem identificação.",
                place=local, found_on=hoje - timedelta(days=rnd.randint(2, 70)),
                status=status, registered_by=equipe[Role.SECRETARIA],
                returned_to="Entregue ao responsável" if status == FoundItem.Status.RETURNED else "",
                closed_at=timezone.now() if status != FoundItem.Status.KEPT else None,
                closed_by=equipe[Role.SECRETARIA] if status != FoundItem.Status.KEPT else None)
            criados.append(it)
        Claim.objects.create(item=criados[0], user=responsaveis[0], student=estudantes[0],
                             description="Tem o nome do meu filho escrito na etiqueta.",
                             status=Claim.Status.PENDING)
        Claim.objects.create(item=criados[3], user=responsaveis[1 % len(responsaveis)],
                             student=estudantes[1], description="Armação azul, lente direita riscada.",
                             status=Claim.Status.ACCEPTED, answered_by=equipe[Role.SECRETARIA],
                             answered_at=timezone.now())

    # -------- comunicação
    def _seed_communication(self, school, ano, turmas, estudantes, equipe,
                            professores, responsaveis, hoje, rnd):
        from apps.communication.models import (
            Announcement, AnnouncementRead, Authorization, AuthorizationResponse,
            Message, Notification, Poll, PollVote, ServiceRequest, Thread)

        A = Announcement
        comunicados = [
            (A.Scope.INSTITUCIONAL, A.Audience.FAMILIA, None, None, "Reunião de pais e mestres",
             "A reunião do bimestre será no próximo sábado, às 9h, no pátio coberto."),
            (A.Scope.INSTITUCIONAL, A.Audience.TODOS, None, None, "Semana da leitura",
             "De segunda a sexta teremos atividades especiais de leitura em todas as turmas."),
            (A.Scope.INSTITUCIONAL, A.Audience.EQUIPE, None, None, "Fechamento de notas",
             "O prazo para lançar as notas do bimestre é sexta-feira."),
            (A.Scope.TURMA, A.Audience.FAMILIA, turmas[0], None, f"Passeio da turma {turmas[0].name}",
             "Enviaremos a autorização do passeio ao parque pela plataforma."),
        ]
        criados = []
        for scope, aud, turma, st, titulo, corpo in comunicados:
            criados.append(Announcement.objects.create(
                school=school, scope=scope, audience=aud, class_group=turma, student=st,
                title=titulo, body=corpo, created_by=equipe[Role.DIRECAO]))
        Announcement.objects.create(
            school=school, scope=A.Scope.INDIVIDUAL, audience=A.Audience.FAMILIA,
            student=estudantes[0], title="Parabéns pelo empenho",
            body="Queremos parabenizar pelo progresso em leitura neste bimestre.",
            created_by=equipe[Role.COORDENACAO])
        for resp in responsaveis[:5]:
            AnnouncementRead.objects.create(announcement=criados[0], user=resp)

        # Conversas entre responsáveis e a equipe.
        for i, resp in enumerate(responsaveis[:5]):
            filho = GuardianLink.objects.filter(guardian=resp, status="aprovado").first()
            aluno = filho.student if filho else estudantes[i]
            prof = professores[i % len(professores)]
            th = Thread.objects.create(
                school=school, student=aluno, title=f"Dúvida sobre {aluno.first_name}",
                created_by=resp)
            th.participants.add(resp, prof)
            Message.objects.create(thread=th, sender=resp,
                                   body="Boa tarde! Gostaria de saber como está o rendimento em matemática.")
            m2 = Message.objects.create(thread=th, sender=prof,
                                        body="Olá! Está indo bem, melhorou bastante nas últimas atividades.")
            m2.read_at = timezone.now()
            m2.save(update_fields=["read_at"])

        Cat, Stt = ServiceRequest.Category, ServiceRequest.Status
        pedidos = [
            (Cat.CADASTRO, "Atualização de telefone", Stt.CONCLUIDA if hasattr(Stt, "CONCLUIDA") else Stt.DONE),
            (Cat.DOCUMENTO, "Declaração de matrícula", Stt.RESPONDED),
            (Cat.DUVIDA, "Dúvida sobre o calendário", Stt.UNDER_REVIEW),
            (Cat.CONTATO, "Gostaria de agendar uma conversa", Stt.RECEIVED),
            (Cat.LGPD, "Acesso aos dados do meu filho", Stt.UNDER_REVIEW),
        ]
        for i, (cat, titulo, status) in enumerate(pedidos):
            resp = responsaveis[i % len(responsaveis)]
            filho = GuardianLink.objects.filter(guardian=resp, status="aprovado").first()
            sr = ServiceRequest.objects.create(
                school=school, requester=resp,
                student=filho.student if filho else None, category=cat,
                data_right=(ServiceRequest.DataRight.ACCESS if cat == Cat.LGPD else ""),
                title=titulo, description="Solicitação de demonstração.", status=status)
            if status in (Stt.RESPONDED, Stt.DONE):
                sr.response = "Pronto, já providenciamos. Qualquer dúvida, estamos à disposição."
                sr.responded_by = equipe[Role.SECRETARIA]
                sr.responded_at = timezone.now()
                sr.save()

        # Autorizações: um passeio e o uso de imagem (vigente).
        passeio = Authorization.objects.create(
            school=school, kind=Authorization.Kind.TRIP, title="Visita ao museu de ciências",
            description="Saída às 8h, retorno às 12h. Levar lanche e boné.",
            event_date=hoje + timedelta(days=14), deadline=hoje + timedelta(days=7),
            created_by=equipe[Role.COORDENACAO])
        passeio.class_groups.add(turmas[0], turmas[1])
        for turma in (turmas[0], turmas[1]):
            for st in self._alunos(turma):
                resp = GuardianLink.objects.filter(student=st, status="aprovado").first()
                if resp and rnd.random() < 0.7:
                    AuthorizationResponse.objects.create(
                        authorization=passeio, student=st,
                        answer=rnd.choice([AuthorizationResponse.Answer.YES,
                                           AuthorizationResponse.Answer.YES,
                                           AuthorizationResponse.Answer.NO]),
                        answered_by=resp.guardian)
        imagem = Authorization.objects.create(
            school=school, kind=Authorization.Kind.IMAGE, title="Uso de imagem em 2026",
            description="Fotos de atividades podem aparecer nos murais e no site da escola.",
            event_date=hoje - timedelta(days=30), valid_until=hoje.replace(month=12, day=31),
            deadline=hoje - timedelta(days=15), created_by=equipe[Role.DIRECAO])
        imagem.class_groups.add(*turmas)

        # Consulta às famílias.
        poll = Poll.objects.create(
            school=school, question="Qual o melhor horário para a reunião de pais?",
            description="Escolha a opção que fica melhor para você.",
            options=["Sábado de manhã", "Terça à noite", "Quinta à tarde"],
            deadline=hoje + timedelta(days=5), created_by=equipe[Role.DIRECAO])
        for i, resp in enumerate(responsaveis[:8]):
            PollVote.objects.create(poll=poll, user=resp, option=i % 3)

        # Alguns avisos na central (sininho) para os responsáveis.
        for resp in responsaveis[:6]:
            Notification.objects.create(
                school=school, user=resp, kind=Notification.Kind.ANNOUNCEMENT,
                title="Reunião de pais e mestres",
                body="Confira o comunicado sobre a reunião do bimestre.",
                priority=Notification.Priority.HIGH)

    # -------- reuniões e atendimentos
    def _seed_meetings(self, school, turmas, estudantes, equipe, professores,
                       responsaveis, hoje, rnd):
        from apps.meetings.models import (
            Meeting, MeetingFollowUp, OfficeHours, OfficeSlot)

        M = Meeting
        fam = Meeting.objects.create(
            school=school, kind=M.Kind.FAMILY, title="Conversa sobre o 1º bimestre",
            student=estudantes[0], scheduled_at=self._aware(hoje + timedelta(days=3), time(14, 0)),
            duration_minutes=30, location="Sala da coordenação",
            agenda="Acompanhamento das atividades e da frequência.",
            created_by=equipe[Role.COORDENACAO])
        fam.participants.add(equipe[Role.COORDENACAO], responsaveis[0])

        conselho = Meeting.objects.create(
            school=school, kind=M.Kind.COUNCIL, title="Conselho de classe — 1º Ano A",
            class_group=turmas[0], scheduled_at=self._aware(hoje - timedelta(days=5), time(9, 0)),
            duration_minutes=60, location="Sala dos professores", status=M.Status.DONE,
            summary="Turma com bom desempenho geral; combinamos reforço em matemática.",
            confidential_notes="Acompanhar dois estudantes com frequência irregular.",
            created_by=equipe[Role.DIRECAO])
        conselho.participants.add(equipe[Role.DIRECAO], equipe[Role.COORDENACAO], *professores[:2])
        MeetingFollowUp.objects.create(
            meeting=conselho, description="Montar grupo de reforço de matemática",
            responsible=professores[0], due_date=hoje + timedelta(days=10),
            status=MeetingFollowUp.Status.PENDING)
        MeetingFollowUp.objects.create(
            meeting=conselho, description="Enviar recado às famílias sobre a reunião",
            responsible=equipe[Role.SECRETARIA], due_date=hoje - timedelta(days=2),
            status=MeetingFollowUp.Status.DONE, done_note="Enviado pela central.",
            done_at=timezone.now(), done_by=equipe[Role.SECRETARIA])

        Meeting.objects.create(
            school=school, kind=M.Kind.PEDAGOGICAL, title="Planejamento da semana pedagógica",
            scheduled_at=self._aware(hoje + timedelta(days=7), time(8, 0)),
            location="Sala multiuso", agenda="Alinhamento das avaliações do bimestre.",
            created_by=equipe[Role.COORDENACAO])

        # Horário de atendimento com alguns horários, um já marcado.
        oh = OfficeHours.objects.create(
            school=school, host=equipe[Role.COORDENACAO], title="Plantão de atendimento às famílias",
            day=hoje + timedelta(days=4), start=time(14, 0), end=time(15, 0),
            slot_minutes=15, location="Sala da coordenação",
            notes="Cada família tem 15 minutos.")
        oh.class_groups.add(turmas[0], turmas[1])
        base = self._aware(oh.day, oh.start)
        for n in range(4):
            inicio = base + timedelta(minutes=15 * n)
            if n == 1:
                reun = Meeting.objects.create(
                    school=school, kind=M.Kind.FAMILY, title="Atendimento — plantão",
                    student=estudantes[1], scheduled_at=inicio, duration_minutes=15,
                    location="Sala da coordenação", created_by=equipe[Role.COORDENACAO])
                reun.participants.add(equipe[Role.COORDENACAO], responsaveis[1 % len(responsaveis)])
                OfficeSlot.objects.create(hours=oh, starts_at=inicio, student=estudantes[1],
                                          booked_by=responsaveis[1 % len(responsaveis)],
                                          booked_at=timezone.now(),
                                          topic="Dúvidas sobre as atividades", meeting=reun)
            else:
                OfficeSlot.objects.create(hours=oh, starts_at=inicio)

    # -------- apoio à inclusão
    def _seed_inclusion(self, school, estudantes, equipe, professores, disciplinas, hoje):
        from apps.inclusion.models import (
            SupportCase, SupportCategory, SupportEvent, SupportNeed, SupportPlan)

        SupportCategory.ensure_defaults(school)
        cats = list(SupportCategory.objects.filter(school=school)[:4])
        for i, st in enumerate(estudantes[:3]):
            case = SupportCase.objects.create(
                school=school, student=st,
                status=SupportCase.Status.ANALYZED if i == 0 else SupportCase.Status.DECLARED,
                has_report=SupportCase.HasReport.YES if i == 0 else SupportCase.HasReport.NO,
                family_notes="Informações compartilhadas pela família na matrícula.",
                declared_by=equipe[Role.SECRETARIA], declared_at=timezone.now(),
                legal_basis=SupportCase.LegalBasis.LEGAL_DUTY)
            if cats:
                case.declared_categories.add(cats[i % len(cats)])
                if i == 0:
                    case.validated_categories.add(cats[0])
                    case.validated_by = equipe[Role.COORDENACAO]
                    case.validated_at = timezone.now()
                    case.save()
            SupportNeed.objects.create(
                case=case, area=SupportNeed.Area.LEARNING,
                description="Apoio na leitura e na organização das tarefas.",
                classroom_strategies="Tempo adicional e instruções em etapas.",
                created_by=equipe[Role.COORDENACAO])
            SupportEvent.objects.create(
                case=case, actor=equipe[Role.SECRETARIA], action="Ficha criada",
                to_status=case.status, note="Registro de demonstração.")
            if i == 0:
                plan = SupportPlan.objects.create(
                    case=case, status=SupportPlan.Status.ACTIVE,
                    starts_on=hoje - timedelta(days=20),
                    review_due=hoje + timedelta(days=180),
                    barriers="Dificuldade de leitura fluente.",
                    strengths="Boa comunicação oral e participação.",
                    objectives="Avançar na leitura de textos curtos.",
                    strategies="Leitura compartilhada e material concreto.",
                    teacher_summary="Dar tempo extra, instruções em etapas e valorizar a participação oral.",
                    created_by=equipe[Role.COORDENACAO])
                plan.responsibles.add(equipe[Role.COORDENACAO], professores[0])

    # -------- metas da escola
    def _seed_analytics(self, school, turmas, equipe, hoje):
        from apps.analytics.models import SchoolGoal

        I = SchoolGoal.Indicator
        metas = [
            (I.ATTENDANCE, Decimal("92.00"), None),
            (I.AVERAGE, Decimal("7.50"), None),
            (I.DELIVERY, Decimal("80.00"), None),
            (I.SKILLS, Decimal("70.00"), turmas[0]),
        ]
        for ind, alvo, turma in metas:
            SchoolGoal.objects.create(
                school=school, indicator=ind, class_group=turma, target=alvo,
                starts_on=hoje - timedelta(days=30), deadline=hoje + timedelta(days=90),
                notes="Meta de demonstração.", created_by=equipe[Role.DIRECAO])

    # -------- rematrícula
    def _seed_reenroll(self, school, ano, turmas, equipe, estudantes, hoje, rnd):
        from apps.reenroll.models import Answer, Campaign
        from apps.reenroll.services import seal_for

        prox = SchoolYear.objects.create(
            school=school, name=str(hoje.year + 1), is_current=False,
            start_date=hoje.replace(year=hoje.year + 1, month=2, day=1),
            end_date=hoje.replace(year=hoje.year + 1, month=12, day=15))
        camp = Campaign.objects.create(
            school=school, target_year=prox, title=f"Rematrícula {hoje.year + 1}",
            message="Confirme a continuidade do seu filho para o próximo ano até o prazo.",
            opens_on=hoje - timedelta(days=5), deadline=hoje + timedelta(days=20),
            announced_at=timezone.now(), created_by=equipe[Role.SECRETARIA])
        camp.class_groups.add(*turmas)
        # Algumas respostas já registradas pela secretaria (presencial).
        for i, st in enumerate(estudantes[:12]):
            sai = i % 6 == 0
            ans = Answer(
                campaign=camp, student=st,
                decision=Answer.Decision.LEAVE if sai else Answer.Decision.STAY,
                reason=Answer.Reason.MOVING if sai else "",
                reason_text="Mudança de cidade." if sai else "",
                answered_by=equipe[Role.SECRETARIA],
                answered_by_name="Rita Camargo (secretaria)", in_person=True,
                answered_at=timezone.now())
            ans.seal = seal_for(ans)
            ans.save()

    # -------- histórico e trajetória (longitudinal)
    def _seed_longitudinal(self, school, estudantes, ano, turmas, equipe, hoje, rnd):
        from apps.longitudinal.models import (
            Outcome, PriorGrade, PriorYear, YearResult)

        comps = ["Língua Portuguesa", "Matemática", "Ciências", "História", "Geografia"]
        for st in estudantes[:24]:
            outcome = rnd.choices(
                [Outcome.APPROVED, Outcome.APPROVED, Outcome.COUNCIL,
                 Outcome.RETAINED, Outcome.TRANSFERRED],
                weights=[6, 6, 2, 1, 1])[0]
            py = PriorYear.objects.create(
                school=school, student=st, year=hoje.year - 1,
                grade_label="Ano anterior", school_name="Escola Demonstração (dados fictícios)",
                outcome=outcome, attendance_percent=Decimal(str(round(rnd.uniform(82, 99), 1))),
                created_by=equipe[Role.SECRETARIA])
            for comp in comps:
                PriorGrade.objects.create(
                    record=py, subject=comp,
                    value=Decimal(str(round(rnd.uniform(5, 10), 1))))

        # Coorte do ano anterior na plataforma, para a análise de retenção
        # (curva de sobrevivência) ter dados: matrículas concluídas com resultado.
        prior = SchoolYear.objects.create(
            school=school, name=str(hoje.year - 1), is_current=False,
            start_date=ano.start_date.replace(year=hoje.year - 1),
            end_date=ano.end_date.replace(year=hoje.year - 1))
        prior_turmas = {
            t.pk: ClassGroup.objects.create(
                school=school, school_year=prior, name=f"{t.name} ({hoje.year - 1})",
                grade=t.grade, turn=t.turn) for t in turmas}
        fim_prior = prior.end_date
        for i, st in enumerate(estudantes[:40]):
            atual = Enrollment.objects.filter(student=st, school_year=ano).first()
            if not atual:
                continue
            prior_turma = prior_turmas[atual.class_group_id]
            resultado = rnd.choices(
                [Outcome.APPROVED, Outcome.COUNCIL, Outcome.TRANSFERRED,
                 Outcome.DROPOUT, Outcome.RETAINED],
                weights=[26, 4, 4, 4, 2])[0]
            if resultado == Outcome.TRANSFERRED:
                status = "transferido"
            elif resultado == Outcome.DROPOUT:
                status = "desistente"
            else:
                status = "concluido"
            enr = Enrollment.objects.create(
                school=school, student=st, class_group=prior_turma, school_year=prior,
                enrollment_number=f"{prior.name}{i + 1:04d}", status=status,
                started_on=prior.start_date, ended_on=fim_prior)
            YearResult.objects.create(
                school=school, enrollment=enr, outcome=resultado,
                decided_by=equipe[Role.DIRECAO])

    # -------- pedagógico avançado: justificativas, planos, rubricas, diário
    def _seed_pedagogy_extras(self, school, turmas, disciplinas, estudantes,
                              professores, equipe, responsaveis, hoje, rnd):
        from apps.curriculum.models import CurriculumItem, component_for, year_for
        from apps.pedagogy.models import (
            AbsenceJustification, ActiveSearchAction, Activity, InterventionPlan,
            LessonPlan, LessonPlanReview, LessonRecord, PlanNote, Rubric,
            RubricCriterion, RubricDescriptor, RubricLevel, RubricScore)

        # Justificativas de falta.
        J = AbsenceJustification.Status
        for i, st in enumerate(estudantes[:5]):
            status = [J.RECEIVED, J.UNDER_REVIEW, J.APPROVED, J.REFUSED, J.RECEIVED][i]
            turma = Enrollment.objects.filter(student=st, status="ativo").first()
            aj = AbsenceJustification.objects.create(
                school=school, student=st,
                class_group=turma.class_group if turma else turmas[0],
                start_date=hoje - timedelta(days=5 + i), end_date=hoje - timedelta(days=4 + i),
                reason="Consulta médica, atestado em anexo (entregue na secretaria).",
                submitted_by=responsaveis[i % len(responsaveis)], status=status)
            if status in (J.APPROVED, J.REFUSED):
                aj.note = "Analisado pela secretaria."
                aj.validated_by = equipe[Role.SECRETARIA]
                aj.validated_at = timezone.now()
                aj.save()

        # Planos de acompanhamento com evolução.
        for i, st in enumerate(estudantes[:3]):
            plano = InterventionPlan.objects.create(
                school=school, student=st, title="Acompanhamento de leitura",
                description="Reforço de leitura e escrita, com acompanhamento quinzenal.",
                success_criterion="Ler um texto curto com fluência até o fim do bimestre.",
                deadline=hoje + (timedelta(days=15) if i else timedelta(days=-3)),
                created_by=equipe[Role.COORDENACAO])
            PlanNote.objects.create(plan=plano, note="Primeiro encontro realizado; boa adesão.",
                                    created_by=equipe[Role.COORDENACAO])
            if i == 0:
                PlanNote.objects.create(plan=plano, note="Evolução na leitura de palavras.",
                                        created_by=professores[0])

        # Planejamentos (um por turma/disciplina, em situações diferentes) e diário.
        def _items(subject, turma, n):
            comp = component_for(subject)
            year = year_for(turma)
            if not comp:
                return []
            return list(CurriculumItem.for_pair(school, comp, year)[:n])

        S = LessonPlan.Status
        estados = [S.DRAFT, S.SUBMITTED, S.APPROVED]
        for i, turma in enumerate(turmas[:3]):
            for j, disc in enumerate(disciplinas[:2]):
                prof = self._teacher_for(turma, disc, professores)
                status = estados[(i + j) % len(estados)]
                lp = LessonPlan.objects.create(
                    school=school, teacher=prof, class_group=turma, subject=disc,
                    starts_on=hoje - timedelta(days=7), ends_on=hoje + timedelta(days=14),
                    title=f"Unidade de {disc.name}", content="Conteúdos do bimestre.",
                    objectives="Objetivos de aprendizagem do período.",
                    methodology="Aulas expositivas, atividades em dupla e jogos.",
                    status=status,
                    submitted_at=timezone.now() if status != S.DRAFT else None)
                its = _items(disc, turma, 3)
                if its:
                    lp.curriculum.add(*its)
                if status == S.APPROVED:
                    LessonPlanReview.objects.create(
                        plan=lp, author=equipe[Role.COORDENACAO], decision=S.APPROVED,
                        comment="Planejamento validado. Bom trabalho!")

        for turma in turmas[:3]:
            for disc in disciplinas[:2]:
                prof = self._teacher_for(turma, disc, professores)
                dia = hoje
                feitos = 0
                while feitos < 3:
                    dia -= timedelta(days=1)
                    if dia.weekday() >= 5:
                        continue
                    feitos += 1
                    lr = LessonRecord.objects.create(
                        school=school, class_group=turma, subject=disc, teacher=prof,
                        date=dia, content=f"Aula de {disc.name}: conteúdo trabalhado em sala.",
                        notes="")
                    its = _items(disc, turma, 2)
                    if its:
                        lr.curriculum.add(*its)

        # Busca ativa de um estudante com muitas faltas.
        K = ActiveSearchAction.Kind
        for n, kind in enumerate([K.PHONE, K.MESSAGE, K.MEETING]):
            ActiveSearchAction.objects.create(
                school=school, student=estudantes[5], date=hoje - timedelta(days=10 - n * 3),
                kind=kind, outcome="Contato com a família; combinado retorno às aulas.",
                recorded_by=equipe[Role.COORDENACAO])

        # Rubrica aplicada a uma atividade publicada.
        disc = disciplinas[1]
        turma = turmas[0]
        rub = Rubric.objects.create(
            school=school, title="Rubrica de produção textual", subject=disc, shared=True,
            description="Critérios para avaliar textos dos estudantes.",
            created_by=self._teacher_for(turma, disc, professores))
        criterios = [
            RubricCriterion.objects.create(rubric=rub, name="Clareza das ideias", order=0),
            RubricCriterion.objects.create(rubric=rub, name="Ortografia e pontuação", order=1),
            RubricCriterion.objects.create(rubric=rub, name="Organização do texto", order=2),
        ]
        niveis = [
            RubricLevel.objects.create(rubric=rub, label="Em desenvolvimento", points=Decimal("1"), order=0),
            RubricLevel.objects.create(rubric=rub, label="Adequado", points=Decimal("2"), order=1),
            RubricLevel.objects.create(rubric=rub, label="Muito bom", points=Decimal("3"), order=2),
        ]
        for c in criterios:
            for lv in niveis:
                RubricDescriptor.objects.create(criterion=c, level=lv,
                                                text=f"{c.name}: {lv.label.lower()}.")
        atividade = Activity.objects.filter(
            school=school, class_group=turma, status=Activity.Status.PUBLISHED).first()
        if atividade:
            for st in self._alunos(turma)[:8]:
                for c in criterios:
                    RubricScore.objects.create(
                        activity=atividade, student=st, criterion=c,
                        level=rnd.choice(niveis),
                        updated_by=atividade.created_by)

    # -------- conteúdos da prova (study)
    def _seed_study(self, school, turmas, disciplinas, estudantes, professores, hoje, rnd):
        from apps.curriculum.models import CurriculumItem, component_for, year_for
        from apps.pedagogy.models import Evaluation
        from apps.study.models import (
            ExamGuide, ExamTopic, PracticeAttempt, PracticeQuestion, StudyMaterial,
            StudyQuestion, TopicCheck)

        for turma in turmas[:2]:
            disc = disciplinas[0]  # Matemática
            prof = self._teacher_for(turma, disc, professores)
            ev = Evaluation.objects.filter(school=school, class_group=turma, subject=disc).first()
            guide = ExamGuide.objects.create(
                school=school, class_group=turma, subject=disc, evaluation=ev,
                title=f"Prova de {disc.name} — {turma.name}",
                exam_date=hoje + timedelta(days=10),
                description="Revise os conteúdos trabalhados no bimestre.",
                guidance="Estude um pouco por dia e refaça os exercícios.",
                status=ExamGuide.Status.PUBLISHED, published_date=hoje - timedelta(days=2),
                created_by=prof)
            comp = component_for(disc)
            year = year_for(turma)
            itens = list(CurriculumItem.for_pair(school, comp, year)[:4]) if comp else []
            if itens:
                guide.curriculum.add(*itens)
            topicos = []
            for n, titulo in enumerate(["Adição e subtração", "Problemas do dia a dia", "Figuras geométricas"]):
                t = ExamTopic.objects.create(
                    guide=guide, title=titulo, description="O que estudar neste tópico.",
                    priority=rnd.choice(["alta", "media", "baixa"]), order=n)
                topicos.append(t)
            StudyMaterial.objects.create(
                guide=guide, topic=topicos[0], kind=StudyMaterial.Kind.LINK,
                title="Vídeo: adição com reagrupamento", url="https://www.khanacademy.org/",
                platform="Khan Academy", why="Explica passo a passo.", order=0,
                created_by=prof)
            StudyMaterial.objects.create(
                guide=guide, topic=topicos[1], kind=StudyMaterial.Kind.EXERCISES,
                title="Lista de problemas resolvidos", description="10 problemas com gabarito.",
                order=1, created_by=prof)
            pq = PracticeQuestion.objects.create(
                guide=guide, topic=topicos[0], statement="Quanto é 27 + 15?",
                options=["32", "42", "41", "52"], correct=1,
                explanation="27 + 15 = 42.", order=0, created_by=prof)
            if itens:
                pq.curriculum.add(itens[0])
            alunos = self._alunos(turma)
            for st in alunos[:10]:
                escolha = 1 if rnd.random() < 0.6 else rnd.choice([0, 2, 3])
                PracticeAttempt.objects.create(question=pq, student=st, chosen=escolha,
                                               is_correct=escolha == 1)
            for st in alunos[:6]:
                TopicCheck.objects.create(topic=rnd.choice(topicos), student=st,
                                          status=rnd.choice(["entendi", "praticar", "duvida"]))
            if alunos:
                StudyQuestion.objects.create(
                    guide=guide, topic=topicos[0], student=alunos[0], author=prof,
                    text="Professor, o tópico 1 cai na prova?")

    # -------- EIA-Cognitio: questões, respostas e observações
    def _seed_cognitio(self, school, turmas, disciplinas, estudantes, professores, hoje, rnd):
        from apps.cognitio.models import (
            MasteryScale, Question, QuestionResponse, QuestionSkill, SkillObservation)
        from apps.curriculum.models import CurriculumItem, component_for, year_for
        from apps.pedagogy.models import Evaluation

        MasteryScale.objects.get_or_create(
            school=school, defaults={"share_with_family": True,
                                     "updated_by": professores[0]})

        for turma in turmas[:3]:
            for disc in disciplinas[:2]:  # Matemática e Língua Portuguesa
                comp = component_for(disc)
                year = year_for(turma)
                if not comp:
                    continue
                itens = list(CurriculumItem.for_pair(school, comp, year)[:4])
                if not itens:
                    continue
                prof = self._teacher_for(turma, disc, professores)
                ev = Evaluation.objects.filter(
                    school=school, class_group=turma, subject=disc).first()
                alunos = self._alunos(turma)
                if ev:
                    for n, item in enumerate(itens):
                        q = Question.objects.create(
                            evaluation=ev, number=n + 1,
                            label=f"Questão sobre {item.code}", max_points=Decimal("1.00"),
                            evidence_type=Question.EvidenceType.OBJECTIVE)
                        QuestionSkill.objects.create(question=q, item=item,
                                                     role=QuestionSkill.Role.MAIN)
                        for st in alunos:
                            r = rnd.random()
                            if r < 0.1:
                                QuestionResponse.objects.create(
                                    question=q, student=st,
                                    status=QuestionResponse.Status.BLANK, updated_by=prof)
                            else:
                                QuestionResponse.objects.create(
                                    question=q, student=st,
                                    status=QuestionResponse.Status.ANSWERED,
                                    points=Decimal(str(round(rnd.uniform(0, 1), 2))),
                                    updated_by=prof)
                # Observações diretas do professor por habilidade.
                for st in alunos[:8]:
                    item = rnd.choice(itens)
                    SkillObservation.objects.create(
                        school=school, student=st, item=item, class_group=turma,
                        subject=disc, teacher=prof,
                        observed_on=hoje - timedelta(days=rnd.randint(3, 25)),
                        level=rnd.choice([2, 3, 3, 4, 5]),
                        context="Resolução de exercícios em sala.",
                        note="Observação de demonstração.")

    def _rebuild_cognitio(self, school):
        """Recalcula evidências por habilidade e gera alertas pedagógicos."""
        try:
            from apps.cognitio.alerts import generate_for_school
            from apps.cognitio.evidence import rebuild_school

            rebuild_school(school)
            generate_for_school(school)
        except Exception as exc:  # pragma: no cover - demonstração resiliente
            self.stdout.write(self.style.WARNING(
                f"EIA-Cognitio: evidências não recalculadas ({exc})."))

    # ---------------------------------------------------------------- apoio
    def _user(self, username, first, last, role, school):
        user = User.objects.create_user(
            username=username, password=DEMO_PASSWORD,
            first_name=first, last_name=last, role=role, school=school,
        )
        # Dados de demonstração não forçam troca de senha: a ideia é poder
        # entrar e olhar.
        return user

    def _resumo_modulos(self, school):
        from apps.booking.models import Booking
        from apps.care.models import HealthIncident, HealthRecord, MedicationRequest
        from apps.cognitio.models import LearningAlert, SkillEvidence, SkillObservation
        from apps.communication.models import (
            Announcement, Authorization, Poll, ServiceRequest, Thread)
        from apps.gate.models import GateEvent, StudentCard
        from apps.inclusion.models import SupportCase
        from apps.library.models import Book, Loan
        from apps.longitudinal.models import PriorYear, YearResult
        from apps.meetings.models import Meeting
        from apps.pedagogy.models import LessonPlan, LessonRecord
        from apps.school_calendar.models import CalendarEvent
        from apps.study.models import ExamGuide
        from apps.workshops.models import Workshop

        w = self.stdout.write
        linhas = [
            ("comunicados", Announcement.objects.filter(school=school).count()),
            ("conversas", Thread.objects.filter(school=school).count()),
            ("solicitações", ServiceRequest.objects.filter(school=school).count()),
            ("autorizações/consultas", Authorization.objects.filter(school=school).count()
             + Poll.objects.filter(school=school).count()),
            ("eventos do calendário", CalendarEvent.objects.filter(school=school).count()),
            ("livros/empréstimos", f"{Book.objects.filter(school=school).count()}/"
             f"{Loan.objects.filter(school=school).count()}"),
            ("fichas de saúde", HealthRecord.objects.filter(school=school).count()),
            ("atendimentos/medicação", f"{HealthIncident.objects.filter(school=school).count()}/"
             f"{MedicationRequest.objects.filter(school=school).count()}"),
            ("carteirinhas/portaria", f"{StudentCard.objects.filter(school=school).count()}/"
             f"{GateEvent.objects.filter(school=school).count()}"),
            ("oficinas", Workshop.objects.filter(school=school).count()),
            ("reuniões", Meeting.objects.filter(school=school).count()),
            ("fichas de inclusão", SupportCase.objects.filter(school=school).count()),
            ("planejamentos/diário", f"{LessonPlan.objects.filter(school=school).count()}/"
             f"{LessonRecord.objects.filter(school=school).count()}"),
            ("conteúdos de prova", ExamGuide.objects.filter(school=school).count()),
            ("anos anteriores/resultados", f"{PriorYear.objects.filter(school=school).count()}/"
             f"{YearResult.objects.filter(school=school).count()}"),
            ("EIA: evidências/obs/alertas", f"{SkillEvidence.objects.filter(school=school).count()}/"
             f"{SkillObservation.objects.filter(school=school).count()}/"
             f"{LearningAlert.objects.filter(school=school).count()}"),
        ]
        w("Módulos preenchidos:")
        for nome, valor in linhas:
            w(f"  {nome} ".ljust(32, ".") + f" {valor}")

    def _resumo(self, school, n_estudantes):
        w = self.stdout.write
        w(self.style.SUCCESS(f"Escola de demonstração criada: {school.name}"))
        w("")
        w(f"  código da escola .... {school.code}")
        w(f"  estudantes .......... {Student.objects.filter(school=school).count()}")
        w(f"  turmas .............. {ClassGroup.objects.filter(school=school).count()}")
        w(f"  disciplinas ......... {Subject.objects.filter(school=school).count()}")
        w(f"  atividades .......... {Activity.objects.filter(school=school).count()}")
        w(f"  entregas ............ {Submission.objects.filter(school=school).count()}")
        w(f"  trabalhos em grupo .. {GroupWork.objects.filter(school=school).count()}")
        w(f"  grupos .............. {WorkGroup.objects.filter(group_work__school=school).count()}")
        w(f"  participações ....... {WorkGroupMember.objects.filter(group__group_work__school=school).count()}")
        w(f"  notas ............... {Grade.objects.filter(school=school).count()}")
        w(f"  frequência .......... {AttendanceRecord.objects.filter(school=school).count()}")
        w(f"  contas .............. {User.objects.filter(school=school).count()}")
        w("")
        self._resumo_modulos(school)
        w("")
        w("Contas (todas com a mesma senha):")
        w(f"  senha ............... {DEMO_PASSWORD}")
        w("  direção ............. demo.direcao")
        w("  coordenação ......... demo.coordenacao")
        w("  secretaria .......... demo.secretaria")
        w("  professores ......... demo.prof1 … demo.prof4")
        w("  responsáveis ........ demo.resp1 … (demo.resp1 tem dois filhos)")
        w("")
        w(
            self.style.WARNING(
                "São dados fictícios, numa escola separada da real. "
                "Remova com: python manage.py seeddemo --limpar"
            )
        )
