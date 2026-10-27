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
from datetime import timedelta

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
        from apps.communication.models import (
            Announcement,
            Message,
            Notification,
            ServiceRequest,
            Thread,
        )
        from apps.pedagogy.models import (
            AbsenceJustification,
            AcademicRule,
            InterventionPlan,
        )
        from apps.registry.models import GuardianProfile

        school = School.objects.filter(code=DEMO_CODE).first()
        if not school:
            self.stdout.write("Nada a remover: escola de demonstração não existe.")
            return

        contas = list(User.objects.filter(school=school).values_list("pk", flat=True))
        estudantes = list(
            Student.objects.filter(school=school).values_list("pk", flat=True)
        )

        with transaction.atomic():
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

        self._resumo(school, n_estudantes)

    # ---------------------------------------------------------------- apoio
    def _user(self, username, first, last, role, school):
        user = User.objects.create_user(
            username=username, password=DEMO_PASSWORD,
            first_name=first, last_name=last, role=role, school=school,
        )
        # Dados de demonstração não forçam troca de senha: a ideia é poder
        # entrar e olhar.
        return user

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
