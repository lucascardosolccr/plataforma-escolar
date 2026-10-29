"""Trabalhos em grupo.

Cobre os 15 cenários da §7.7 do Prompt 5 mais os casos de borda que ele pede
(turma sem estudantes, grupo de um, transferidos, sem anexos, sem autorização).

O eixo dos testes é o requisito central da §7.3: todo usuário autorizado
identifica o trabalho, o prazo, a turma, o grupo e QUEM participa — e o
responsável consegue ver os nomes dos colegas do grupo do filho sem que isso
abra caminho para a ficha deles.
"""

import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.core.models import AuditLog, Role, School
from apps.registry.models import Enrollment, GuardianLink, Student

from ..models import (
    GroupWork,
    GroupWorkAttachment,
    GroupWorkDelivery,
    WorkGroup,
    WorkGroupMember,
)

User = get_user_model()
PW = "senha-forte-1"


class GroupWorkBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola A", code="a")
        self.year = SchoolYear.objects.create(school=self.school, name="2026")
        self.turma = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="4º Ano A"
        )
        self.turma_b = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="4º Ano B"
        )
        self.turma_vazia = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="5º Ano A"
        )
        self.cie = Subject.objects.create(school=self.school, name="Ciências")
        self.port = Subject.objects.create(school=self.school, name="Língua Portuguesa")

        def mk(username, role):
            return User.objects.create_user(
                username=username, password=PW, role=role, school=self.school
            )

        self.admin = mk("adm", Role.ADMIN)
        self.coord = mk("coord", Role.COORDENACAO)
        self.sec = mk("sec", Role.SECRETARIA)
        self.prof = mk("prof", Role.PROFESSOR)
        self.prof2 = mk("prof2", Role.PROFESSOR)
        TeacherAssignment.objects.create(
            school=self.school, school_year=self.year, teacher=self.prof,
            class_group=self.turma, subject=self.cie,
        )
        TeacherAssignment.objects.create(
            school=self.school, school_year=self.year, teacher=self.prof,
            class_group=self.turma_vazia, subject=self.cie,
        )
        TeacherAssignment.objects.create(
            school=self.school, school_year=self.year, teacher=self.prof2,
            class_group=self.turma_b, subject=self.port,
        )

        # Quatro alunos na turma, como o exemplo da §7.3.
        self.alunos = []
        for nome in ("Ana", "Bruno", "Carla", "Davi"):
            st = Student.objects.create(school=self.school, first_name=nome)
            Enrollment.objects.create(
                school=self.school, student=st, class_group=self.turma,
                school_year=self.year,
            )
            self.alunos.append(st)
        self.ana, self.bruno, self.carla, self.davi = self.alunos

        # Aluno de outra turma, para o teste de turma cruzada.
        self.outro = Student.objects.create(school=self.school, first_name="Elisa")
        Enrollment.objects.create(
            school=self.school, student=self.outro, class_group=self.turma_b,
            school_year=self.year,
        )

        # Responsável da Ana, e um responsável sem vínculo.
        self.resp_ana = mk("resp_ana", Role.RESPONSAVEL)
        GuardianLink.objects.create(
            school=self.school, guardian=self.resp_ana, student=self.ana,
            status="aprovado",
        )
        self.resp_bruno = mk("resp_bruno", Role.RESPONSAVEL)
        GuardianLink.objects.create(
            school=self.school, guardian=self.resp_bruno, student=self.bruno,
            status="aprovado",
        )
        self.resp_sem_vinculo = mk("resp_zero", Role.RESPONSAVEL)

        # Conta de estudante para a Ana.
        self.conta_ana = mk("aluno_ana", Role.ESTUDANTE)
        self.ana.user = self.conta_ana
        self.ana.save(update_fields=["user"])

    def login(self, username):
        self.assertTrue(self.client.login(username=username, password=PW))

    def payload(self, **extra):
        data = {
            "class_group": self.turma.pk,
            "subject": self.cie.pk,
            "title": "Pesquisa sobre o meio ambiente",
            "description": "Pesquisar e apresentar um cartaz sobre a nascente do bairro.",
            "published_date": "2026-03-01",
            "delivery_mode": GroupWork.DeliveryMode.GROUP,
        }
        data.update(extra)
        return data

    def make_work(self, **extra):
        defaults = dict(
            school=self.school,
            class_group=self.turma,
            subject=self.cie,
            title="Pesquisa sobre o meio ambiente",
            description="Pesquisar e apresentar um cartaz.",
            created_by=self.prof,
            status=GroupWork.Status.PUBLISHED,
            published_date=date(2026, 3, 1),
        )
        defaults.update(extra)
        return GroupWork.objects.create(**defaults)

    def make_group(self, work, nome, alunos):
        g = WorkGroup.objects.create(group_work=work, name=nome)
        for st in alunos:
            WorkGroupMember.objects.create(group=g, student=st, added_by=self.prof)
        return g


class CriacaoEPublicacaoTests(GroupWorkBase):
    """Cenários 1, 2, 5 e 15 da §7.7."""

    def test_professor_creates_work_for_own_class(self):
        self.login("prof")
        resp = self.client.post(
            reverse("pedagogy:group_work_create"), self.payload(_publish="1")
        )
        work = GroupWork.objects.get(title="Pesquisa sobre o meio ambiente")
        self.assertEqual(work.class_group, self.turma)
        self.assertEqual(work.subject, self.cie)
        self.assertEqual(work.status, GroupWork.Status.PUBLISHED)
        self.assertEqual(work.created_by, self.prof)
        # Vai direto para a organização dos grupos.
        self.assertRedirects(
            resp, reverse("pedagogy:group_work_groups", args=[work.pk])
        )

    def test_saved_without_publish_becomes_draft(self):
        self.login("prof")
        self.client.post(reverse("pedagogy:group_work_create"), self.payload())
        work = GroupWork.objects.get(title="Pesquisa sobre o meio ambiente")
        self.assertEqual(work.status, GroupWork.Status.DRAFT)

    def test_only_title_and_description_are_required(self):
        """A §7.1 pede para não obrigar campo que a atividade não precisa."""
        self.login("prof")
        self.client.post(reverse("pedagogy:group_work_create"), self.payload())
        work = GroupWork.objects.get(title="Pesquisa sobre o meio ambiente")
        self.assertEqual(work.objectives, "")
        self.assertEqual(work.guidelines, "")
        self.assertIsNone(work.deadline)

    def test_missing_description_is_rejected(self):
        self.login("prof")
        resp = self.client.post(
            reverse("pedagogy:group_work_create"), self.payload(description="")
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(GroupWork.objects.exists())

    def test_one_work_is_shared_not_duplicated_per_student(self):
        """Cenário 15: quatro alunos num grupo não geram quatro trabalhos."""
        work = self.make_work()
        self.make_group(work, "Grupo 1", self.alunos)
        self.assertEqual(GroupWork.objects.count(), 1)
        self.assertEqual(WorkGroup.objects.count(), 1)
        self.assertEqual(WorkGroupMember.objects.count(), 4)

    def test_deadline_before_publication_is_rejected(self):
        self.login("prof")
        resp = self.client.post(
            reverse("pedagogy:group_work_create"),
            self.payload(published_date="2026-03-10", deadline="2026-03-01"),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "não pode ser anterior")
        self.assertFalse(GroupWork.objects.exists())

    def test_publishing_notifies_guardians_naming_the_student(self):
        from apps.communication.models import Notification

        self.login("prof")
        self.client.post(
            reverse("pedagogy:group_work_create"), self.payload(_publish="1")
        )
        work = GroupWork.objects.get(title="Pesquisa sobre o meio ambiente")
        # Sem grupos, o aviso espera: a família abriria uma tela sem o grupo.
        self.assertFalse(Notification.objects.filter(user=self.resp_ana).exists())
        g = self.make_group(work, "Grupo 1", [])
        self.client.post(
            reverse("pedagogy:group_work_groups", args=[work.pk]),
            {"_acao": "atribuir", f"grupo_{self.ana.pk}": g.pk},
        )
        notif = Notification.objects.filter(
            user=self.resp_ana, title__contains="Pesquisa sobre o meio ambiente"
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn("Ana", notif.body)
        # Bruno não está em grupo nenhum: a família dele não é avisada.
        self.assertFalse(Notification.objects.filter(user=self.resp_bruno).exists())
        # Salvar a composição de novo não avisa em dobro.
        self.client.post(
            reverse("pedagogy:group_work_groups", args=[work.pk]),
            {"_acao": "atribuir", f"grupo_{self.ana.pk}": g.pk, f"grupo_{self.bruno.pk}": g.pk},
        )
        self.assertEqual(Notification.objects.filter(user=self.resp_ana).count(), 1)

    def test_draft_does_not_notify(self):
        from apps.communication.models import Notification

        self.login("prof")
        self.client.post(reverse("pedagogy:group_work_create"), self.payload())
        self.assertEqual(Notification.objects.count(), 0)


class FormacaoDeGruposTests(GroupWorkBase):
    """Cenários 3, 4, 12 e os casos de borda da §7.2."""

    def setUp(self):
        super().setUp()
        self.work = self.make_work()
        self.url = reverse("pedagogy:group_work_groups", args=[self.work.pk])
        self.login("prof")

    def test_creates_group(self):
        self.client.post(self.url, {"_acao": "criar", "name": "Grupo 1"})
        self.assertTrue(self.work.groups.filter(name="Grupo 1").exists())

    def test_duplicate_group_name_is_rejected(self):
        self.client.post(self.url, {"_acao": "criar", "name": "Grupo 1"})
        resp = self.client.post(self.url, {"_acao": "criar", "name": "grupo 1"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Já existe um grupo")
        self.assertEqual(self.work.groups.count(), 1)

    def test_assigns_several_students_at_once(self):
        g = self.make_group(self.work, "Grupo 1", [])
        self.client.post(
            self.url,
            {
                "_acao": "atribuir",
                f"grupo_{self.ana.pk}": g.pk,
                f"grupo_{self.bruno.pk}": g.pk,
                f"grupo_{self.carla.pk}": g.pk,
                f"grupo_{self.davi.pk}": g.pk,
            },
        )
        self.assertEqual(g.active_members().count(), 4)

    def test_moving_a_student_preserves_the_previous_participation(self):
        """Cenário 12 + §7.4: sair do grupo não apaga o histórico."""
        g1 = self.make_group(self.work, "Grupo 1", [self.ana, self.bruno])
        g2 = self.make_group(self.work, "Grupo 2", [self.carla])
        self.client.post(
            self.url,
            {
                "_acao": "atribuir",
                f"grupo_{self.ana.pk}": g2.pk,
                f"grupo_{self.bruno.pk}": g1.pk,
                f"grupo_{self.carla.pk}": g2.pk,
                f"grupo_{self.davi.pk}": "",
            },
        )
        self.assertEqual(set(m.student for m in g2.active_members()), {self.ana, self.carla})
        self.assertEqual(set(m.student for m in g1.active_members()), {self.bruno})
        # A linha antiga continua existindo, marcada como saída.
        antiga = WorkGroupMember.objects.get(group=g1, student=self.ana)
        self.assertIsNotNone(antiga.removed_at)

    def test_removing_from_all_groups_keeps_history(self):
        g = self.make_group(self.work, "Grupo 1", [self.ana])
        self.client.post(self.url, {"_acao": "atribuir", f"grupo_{self.ana.pk}": ""})
        self.assertEqual(g.active_members().count(), 0)
        self.assertTrue(WorkGroupMember.objects.filter(group=g, student=self.ana).exists())

    def test_rejoining_reactivates_instead_of_duplicating(self):
        g = self.make_group(self.work, "Grupo 1", [self.ana])
        self.client.post(self.url, {"_acao": "atribuir", f"grupo_{self.ana.pk}": ""})
        self.client.post(self.url, {"_acao": "atribuir", f"grupo_{self.ana.pk}": g.pk})
        self.assertEqual(
            WorkGroupMember.objects.filter(group=g, student=self.ana).count(), 1
        )
        self.assertEqual(g.active_members().count(), 1)

    def test_student_from_another_class_is_not_offered_nor_accepted(self):
        g = self.make_group(self.work, "Grupo 1", [])
        resp = self.client.get(self.url)
        self.assertNotContains(resp, "Elisa")
        self.client.post(
            self.url, {"_acao": "atribuir", f"grupo_{self.outro.pk}": g.pk}
        )
        self.assertEqual(g.active_members().count(), 0)

    def test_auto_distribution_forms_groups_and_can_be_reviewed(self):
        self.client.post(self.url, {"_acao": "sortear", "quantidade": "2"})
        self.assertEqual(self.work.groups.count(), 2)
        total = WorkGroupMember.objects.filter(
            group__group_work=self.work, removed_at__isnull=True
        ).count()
        self.assertEqual(total, 4)
        # A tela de revisão continua acessível depois do sorteio.
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_auto_distribution_rejects_invalid_count(self):
        for valor in ("0", "-3", "abc", ""):
            resp = self.client.post(
                self.url, {"_acao": "sortear", "quantidade": valor}, follow=True
            )
            self.assertEqual(resp.status_code, 200, f"quantidade={valor!r}")
        self.assertEqual(self.work.groups.count(), 0)

    def test_single_member_group_is_allowed(self):
        g = self.make_group(self.work, "Grupo solo", [self.ana])
        self.assertEqual(g.active_members().count(), 1)
        resp = self.client.get(
            reverse("pedagogy:group_work_detail", args=[self.work.pk])
        )
        self.assertContains(resp, "Grupo solo")

    def test_whole_class_in_one_group(self):
        """A §7.2 pede permitir um único grupo para trabalho coletivo."""
        g = self.make_group(self.work, "Turma inteira", self.alunos)
        self.assertEqual(g.active_members().count(), 4)

    def test_class_without_students_does_not_break(self):
        work = self.make_work(class_group=self.turma_vazia, title="Trabalho sem turma")
        resp = self.client.get(
            reverse("pedagogy:group_work_groups", args=[work.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "não tem estudantes matriculados")

    def test_removing_an_empty_group_is_audited(self):
        g = self.make_group(self.work, "Grupo 1", [])
        self.client.post(self.url, {"_acao": "remover_grupo", "grupo": g.pk})
        self.assertFalse(WorkGroup.objects.filter(pk=g.pk).exists())
        self.assertTrue(
            AuditLog.objects.filter(detail__contains="Removeu o grupo Grupo 1").exists()
        )

    def test_group_with_history_is_not_deleted(self):
        """Apagar o grupo apagaria em cascata a participação e as entregas."""
        g = self.make_group(self.work, "Grupo 1", [self.ana])
        resp = self.client.post(
            self.url, {"_acao": "remover_grupo", "grupo": g.pk}, follow=True
        )
        self.assertTrue(WorkGroup.objects.filter(pk=g.pk).exists())
        self.assertTrue(WorkGroupMember.objects.filter(group=g, student=self.ana).exists())
        self.assertContains(resp, "já tem histórico")

    def test_group_with_delivery_is_not_deleted_even_in_draft(self):
        rascunho = self.make_work(title="Rascunho", status=GroupWork.Status.DRAFT)
        g = self.make_group(rascunho, "Grupo 1", [self.ana])
        GroupWorkDelivery.objects.create(group_work=rascunho, group=g, grade=Decimal("8"))
        self.client.post(
            reverse("pedagogy:group_work_groups", args=[rascunho.pk]),
            {"_acao": "remover_grupo", "grupo": g.pk},
        )
        self.assertTrue(GroupWorkDelivery.objects.filter(group=g).exists())

    def test_draft_group_without_deliveries_may_be_deleted(self):
        rascunho = self.make_work(title="Rascunho", status=GroupWork.Status.DRAFT)
        g = self.make_group(rascunho, "Grupo 1", [self.ana])
        self.client.post(
            reverse("pedagogy:group_work_groups", args=[rascunho.pk]),
            {"_acao": "remover_grupo", "grupo": g.pk},
        )
        self.assertFalse(WorkGroup.objects.filter(pk=g.pk).exists())

    def test_draw_does_not_wipe_published_composition(self):
        g = self.make_group(self.work, "Grupo 1", [self.ana, self.bruno])
        resp = self.client.post(
            self.url, {"_acao": "sortear", "quantidade": "2"}, follow=True
        )
        self.assertTrue(WorkGroup.objects.filter(pk=g.pk).exists())
        self.assertEqual(self.work.groups.count(), 1)
        self.assertContains(resp, "só é possível enquanto")

    def test_draw_does_not_wipe_deliveries(self):
        rascunho = self.make_work(title="Rascunho", status=GroupWork.Status.DRAFT)
        g = self.make_group(rascunho, "Grupo 1", [self.ana])
        GroupWorkDelivery.objects.create(group_work=rascunho, group=g, grade=Decimal("9"))
        self.client.post(
            reverse("pedagogy:group_work_groups", args=[rascunho.pk]),
            {"_acao": "sortear", "quantidade": "2"},
        )
        self.assertEqual(GroupWorkDelivery.objects.filter(group_work=rascunho).count(), 1)

    def test_draw_still_works_before_composition_exists(self):
        self.client.post(self.url, {"_acao": "sortear", "quantidade": "2"})
        self.assertEqual(self.work.groups.count(), 2)
        self.assertEqual(
            WorkGroupMember.objects.filter(group__group_work=self.work).count(), 4
        )

    def test_canceled_work_composition_is_frozen(self):
        g = self.make_group(self.work, "Grupo 1", [self.ana])
        self.work.status = GroupWork.Status.CANCELED
        self.work.save()
        self.client.post(self.url, {"_acao": "atribuir", f"grupo_{self.ana.pk}": ""})
        self.client.post(self.url, {"_acao": "criar", "name": "Grupo 2"})
        self.assertTrue(
            WorkGroupMember.objects.filter(
                group=g, student=self.ana, removed_at__isnull=True
            ).exists()
        )
        self.assertEqual(self.work.groups.count(), 1)
        resp = self.client.get(self.url)
        self.assertContains(resp, "não pode mais ser alterada")
        self.assertNotContains(resp, "Salvar composição")


class VisualizacaoTests(GroupWorkBase):
    """Cenários 6, 7, 8, 9 e 14 — o requisito central da §7.3."""

    def setUp(self):
        super().setUp()
        self.work = self.make_work(deadline=date(2026, 12, 20))
        self.g1 = self.make_group(self.work, "Grupo Nascente", [self.ana, self.bruno])
        self.g2 = self.make_group(self.work, "Grupo Mata", [self.carla, self.davi])

    def test_detail_shows_what_the_work_is_class_subject_and_deadline(self):
        self.login("prof")
        resp = self.client.get(
            reverse("pedagogy:group_work_detail", args=[self.work.pk])
        )
        self.assertContains(resp, "Pesquisa sobre o meio ambiente")
        self.assertContains(resp, "Pesquisar e apresentar um cartaz")
        self.assertContains(resp, "4º Ano A")
        self.assertContains(resp, "Ciências")
        self.assertContains(resp, "20/12/2026")

    def test_teacher_sees_all_groups_and_members(self):
        self.login("prof")
        resp = self.client.get(
            reverse("pedagogy:group_work_detail", args=[self.work.pk])
        )
        for nome in ("Grupo Nascente", "Grupo Mata", "Ana", "Bruno", "Carla", "Davi"):
            self.assertContains(resp, nome)

    def test_work_appears_in_each_members_record(self):
        """Cenário 6: no registro de cada um dos integrantes."""
        self.login("coord")
        for st in self.alunos:
            resp = self.client.get(reverse("student_detail", args=[st.pk]))
            self.assertContains(
                resp, "Pesquisa sobre o meio ambiente", msg_prefix=str(st)
            )

    def test_record_shows_group_name_and_colleagues(self):
        """Cenário 7: a composição correta, no registro individual."""
        self.login("coord")
        resp = self.client.get(reverse("student_detail", args=[self.ana.pk]))
        self.assertContains(resp, "Grupo Nascente")
        self.assertContains(resp, "Bruno")
        # O colega do OUTRO grupo não entra na composição da Ana.
        self.assertNotContains(resp, "Grupo Mata")

    def test_guardian_sees_work_in_own_childs_context(self):
        """Cenário 8: no contexto do próprio filho, com o nome dele explícito."""
        self.login("resp_ana")
        resp = self.client.get(reverse("pedagogy:group_work_list"))
        self.assertContains(resp, "Pesquisa sobre o meio ambiente")
        self.assertContains(resp, "Ana")
        self.assertContains(resp, "Grupo Nascente")

    def test_guardian_identifies_the_colleagues_of_the_group(self):
        """Cenário 9: os responsáveis conseguem identificar os colegas."""
        self.login("resp_ana")
        resp = self.client.get(reverse("pedagogy:group_work_list"))
        self.assertContains(resp, "Bruno")

    def test_guardian_does_not_see_the_other_groups_composition(self):
        """Minimização: a composição dos outros grupos não é necessária."""
        self.login("resp_ana")
        for url in (
            reverse("pedagogy:group_work_list"),
            reverse("pedagogy:group_work_detail", args=[self.work.pk]),
        ):
            resp = self.client.get(url)
            self.assertNotContains(resp, "Grupo Mata")
            self.assertNotContains(resp, "Carla")
            self.assertNotContains(resp, "Davi")

    def test_detail_states_which_student_the_record_refers_to(self):
        """Item 6 da §7.3: qual estudante está consultando o registro."""
        self.login("resp_ana")
        resp = self.client.get(
            reverse("pedagogy:group_work_detail", args=[self.work.pk])
        )
        self.assertContains(resp, "registro de")
        self.assertContains(resp, "Ana")

    def test_student_sees_own_group_and_colleagues(self):
        self.login("aluno_ana")
        resp = self.client.get(reverse("pedagogy:group_work_list"))
        self.assertContains(resp, "Pesquisa sobre o meio ambiente")
        self.assertContains(resp, "Grupo Nascente")
        self.assertContains(resp, "Bruno")
        self.assertNotContains(resp, "Carla")

    def test_colleague_names_are_not_links_for_family(self):
        """A lista de integrantes não pode ser caminho para a ficha do colega."""
        self.login("resp_ana")
        for url in (
            reverse("pedagogy:group_work_list"),
            reverse("pedagogy:group_work_detail", args=[self.work.pk]),
        ):
            corpo = self.client.get(url).content.decode()
            self.assertNotIn(
                reverse("student_detail", args=[self.bruno.pk]),
                corpo,
                f"vazou link para a ficha do colega em {url}",
            )

    def test_deadline_states_are_shown(self):
        """Cenário 14: prazos e situações corretos."""
        hoje = timezone.localdate()
        vencido = self.make_work(
            title="Trabalho vencido", deadline=hoje - timedelta(days=3)
        )
        self.make_group(vencido, "G", [self.ana])
        a_vencer = self.make_work(
            title="Trabalho a vencer", deadline=hoje + timedelta(days=1)
        )
        self.make_group(a_vencer, "G", [self.ana])
        self.login("resp_ana")
        resp = self.client.get(reverse("pedagogy:group_work_list"))
        self.assertContains(resp, "Prazo encerrado")
        self.assertContains(resp, "A vencer")

    def test_student_without_group_does_not_see_the_work(self):
        """Quem não foi colocado em nenhum grupo não tem o que acompanhar."""
        sozinho = Student.objects.create(school=self.school, first_name="Fabio")
        Enrollment.objects.create(
            school=self.school, student=sozinho, class_group=self.turma,
            school_year=self.year,
        )
        resp_f = User.objects.create_user(
            username="resp_fabio", password=PW, role=Role.RESPONSAVEL,
            school=self.school,
        )
        GuardianLink.objects.create(
            school=self.school, guardian=resp_f, student=sozinho, status="aprovado"
        )
        self.login("resp_fabio")
        resp = self.client.get(reverse("pedagogy:group_work_list"))
        self.assertNotContains(resp, "Pesquisa sobre o meio ambiente")

    def test_transferred_student_keeps_participation_history(self):
        Enrollment.objects.filter(student=self.ana, class_group=self.turma).update(
            status="transferido"
        )
        self.login("coord")
        resp = self.client.get(reverse("student_detail", args=[self.ana.pk]))
        self.assertContains(resp, "Pesquisa sobre o meio ambiente")
        self.assertContains(resp, "Grupo Nascente")

    def test_no_template_syntax_leaks_into_the_page(self):
        """Comentário Django `{# #}` é de UMA linha; multilinha vaza como texto.

        Esse defeito já aconteceu aqui: um comentário de duas linhas apareceu
        na tela da família, no meio da lista de colegas.
        """
        paginas = [
            ("prof", reverse("pedagogy:group_work_list")),
            ("prof", reverse("pedagogy:group_work_detail", args=[self.work.pk])),
            ("prof", reverse("pedagogy:group_work_groups", args=[self.work.pk])),
            ("prof", reverse("pedagogy:group_work_deliveries", args=[self.work.pk])),
            ("resp_ana", reverse("pedagogy:group_work_list")),
            ("resp_ana", reverse("pedagogy:group_work_detail", args=[self.work.pk])),
            ("aluno_ana", reverse("pedagogy:group_work_list")),
            ("coord", reverse("student_detail", args=[self.ana.pk])),
        ]
        for quem, url in paginas:
            self.login(quem)
            corpo = self.client.get(url).content.decode()
            for marca in ("{#", "#}", "{%", "%}", "{{", "}}"):
                self.assertNotIn(
                    marca, corpo, f"sintaxe de template vazou em {url} como {quem}"
                )
            self.client.logout()

    def test_work_without_attachments_renders(self):
        self.login("resp_ana")
        resp = self.client.get(
            reverse("pedagogy:group_work_detail", args=[self.work.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Nenhum arquivo")


class PermissoesTests(GroupWorkBase):
    """Cenários 10 e 11, e §7.6."""

    def setUp(self):
        super().setUp()
        self.work = self.make_work()
        self.g1 = self.make_group(self.work, "Grupo Nascente", [self.ana, self.bruno])

    def test_unauthorized_teacher_cannot_change_groups(self):
        """Cenário 11."""
        self.login("prof2")
        for url in (
            reverse("pedagogy:group_work_groups", args=[self.work.pk]),
            reverse("pedagogy:group_work_edit", args=[self.work.pk]),
            reverse("pedagogy:group_work_cancel", args=[self.work.pk]),
            reverse("pedagogy:group_work_deliveries", args=[self.work.pk]),
        ):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_unauthorized_teacher_post_is_also_blocked(self):
        self.login("prof2")
        resp = self.client.post(
            reverse("pedagogy:group_work_groups", args=[self.work.pk]),
            {"_acao": "criar", "name": "Invasor"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(self.work.groups.filter(name="Invasor").exists())

    def test_teacher_cannot_mix_class_and_subject_from_different_assignments(self):
        TeacherAssignment.objects.create(
            school=self.school, school_year=self.year, teacher=self.prof,
            class_group=self.turma_b, subject=self.port,
        )
        self.login("prof")
        resp = self.client.post(
            reverse("pedagogy:group_work_create"),
            self.payload(subject=self.port.pk, title="Par cruzado", _publish="1"),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "não tem atribuição")
        self.assertFalse(GroupWork.objects.filter(title="Par cruzado").exists())

    def test_guardian_without_link_cannot_open_the_work(self):
        self.login("resp_zero")
        self.assertEqual(
            self.client.get(
                reverse("pedagogy:group_work_detail", args=[self.work.pk])
            ).status_code,
            403,
        )

    def test_guardian_cannot_reach_private_data_of_colleagues(self):
        """Cenário 10: ver o nome do colega não dá acesso à ficha dele."""
        self.login("resp_ana")
        self.assertEqual(
            self.client.get(reverse("student_detail", args=[self.bruno.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse("analytics:student_dashboard", args=[self.bruno.pk])
            ).status_code,
            403,
        )

    def test_guardian_cannot_filter_by_unrelated_student(self):
        self.login("resp_ana")
        resp = self.client.get(
            reverse("pedagogy:group_work_list"), {"estudante": self.carla.pk}
        )
        self.assertEqual(resp.status_code, 403)

    def test_draft_is_invisible_to_family_even_by_id(self):
        rascunho = self.make_work(
            title="Rascunho oculto", status=GroupWork.Status.DRAFT
        )
        self.make_group(rascunho, "G", [self.ana])
        self.login("resp_ana")
        self.assertNotContains(
            self.client.get(reverse("pedagogy:group_work_list")), "Rascunho oculto"
        )
        self.assertEqual(
            self.client.get(
                reverse("pedagogy:group_work_detail", args=[rascunho.pk])
            ).status_code,
            403,
        )

    def test_scheduled_work_is_hidden_until_the_date(self):
        futuro = self.make_work(
            title="Agendado para depois",
            published_date=timezone.localdate() + timedelta(days=5),
        )
        self.make_group(futuro, "G", [self.ana])
        self.login("resp_ana")
        self.assertNotContains(
            self.client.get(reverse("pedagogy:group_work_list")), "Agendado para depois"
        )
        self.assertEqual(
            self.client.get(
                reverse("pedagogy:group_work_detail", args=[futuro.pk])
            ).status_code,
            403,
        )

    def test_student_cannot_manage_anything(self):
        self.login("aluno_ana")
        for url in (
            reverse("pedagogy:group_work_create"),
            reverse("pedagogy:group_work_groups", args=[self.work.pk]),
            reverse("pedagogy:group_work_edit", args=[self.work.pk]),
            reverse("pedagogy:group_work_deliveries", args=[self.work.pk]),
        ):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_staff_can_follow_without_managing(self):
        for who in ("coord", "sec", "adm"):
            self.login(who)
            resp = self.client.get(
                reverse("pedagogy:group_work_detail", args=[self.work.pk])
            )
            self.assertEqual(resp.status_code, 200, who)
            self.assertEqual(
                self.client.get(
                    reverse("pedagogy:group_work_groups", args=[self.work.pk])
                ).status_code,
                403,
                f"{who} não deveria organizar grupos",
            )
            self.client.logout()


class CancelamentoTests(GroupWorkBase):
    """Cenário 13."""

    def setUp(self):
        super().setUp()
        self.work = self.make_work()
        self.g1 = self.make_group(self.work, "Grupo Nascente", [self.ana, self.bruno])
        GroupWorkDelivery.objects.create(
            group_work=self.work, group=self.g1, status="entregue",
            registered_by=self.prof,
        )

    def test_cancel_preserves_groups_members_and_deliveries(self):
        self.login("prof")
        self.client.post(
            reverse("pedagogy:group_work_cancel", args=[self.work.pk]),
            {"cancel_reason": "Conteúdo adiado"},
        )
        self.work.refresh_from_db()
        self.assertEqual(self.work.status, GroupWork.Status.CANCELED)
        self.assertEqual(self.work.cancel_reason, "Conteúdo adiado")
        self.assertTrue(GroupWork.objects.filter(pk=self.work.pk).exists())
        self.assertEqual(self.g1.active_members().count(), 2)
        self.assertEqual(GroupWorkDelivery.objects.filter(group=self.g1).count(), 1)

    def test_cancel_requires_reason(self):
        self.login("prof")
        resp = self.client.post(
            reverse("pedagogy:group_work_cancel", args=[self.work.pk]),
            {"cancel_reason": ""},
        )
        self.assertEqual(resp.status_code, 200)
        self.work.refresh_from_db()
        self.assertEqual(self.work.status, GroupWork.Status.PUBLISHED)

    def test_family_sees_it_as_canceled_with_the_reason(self):
        # Estado que o cancelamento real produz para um trabalho já visto.
        self.work.status = GroupWork.Status.CANCELED
        self.work.cancel_reason = "Conteúdo adiado"
        self.work.visible_before_cancel = True
        self.work.save(update_fields=["status", "cancel_reason", "visible_before_cancel"])
        self.login("resp_ana")
        resp = self.client.get(reverse("pedagogy:group_work_list"))
        self.assertContains(resp, "Cancelado")
        self.assertContains(resp, "Conteúdo adiado")


class EntregaTests(GroupWorkBase):
    """§7.5: a regra de entrega é explícita e não contamina os colegas."""

    def setUp(self):
        super().setUp()
        self.work = self.make_work()
        self.g1 = self.make_group(self.work, "Grupo 1", [self.ana, self.bruno])
        self.url = reverse("pedagogy:group_work_deliveries", args=[self.work.pk])
        self.login("prof")

    def test_group_mode_registers_one_row_for_the_group(self):
        self.client.post(
            self.url,
            {
                f"status_{self.g1.pk}_grupo": "entregue",
                f"data_{self.g1.pk}_grupo": "2026-03-20",
                f"nota_{self.g1.pk}_grupo": "9,5",
            },
        )
        d = GroupWorkDelivery.objects.get(group=self.g1)
        self.assertIsNone(d.student)
        self.assertEqual(d.status, "entregue")
        self.assertEqual(str(d.grade), "9.50")
        self.assertEqual(d.delivered_at, date(2026, 3, 20))

    def test_individual_mode_does_not_mark_the_whole_group(self):
        """Marcar um integrante não pode marcar os colegas."""
        self.work.delivery_mode = GroupWork.DeliveryMode.INDIVIDUAL
        self.work.save(update_fields=["delivery_mode"])
        self.client.post(
            self.url, {f"status_{self.g1.pk}_{self.ana.pk}": "entregue"}
        )
        self.assertEqual(
            GroupWorkDelivery.objects.filter(group=self.g1).count(), 1
        )
        d = GroupWorkDelivery.objects.get(group=self.g1)
        self.assertEqual(d.student, self.ana)
        self.assertFalse(
            GroupWorkDelivery.objects.filter(group=self.g1, student=self.bruno).exists()
        )

    def test_blank_status_creates_no_record(self):
        self.client.post(self.url, {f"status_{self.g1.pk}_grupo": ""})
        self.assertEqual(GroupWorkDelivery.objects.count(), 0)

    def test_invalid_grade_is_ignored_not_fatal(self):
        for valor in ("abc", "-2", "99999"):
            resp = self.client.post(
                self.url,
                {
                    f"status_{self.g1.pk}_grupo": "entregue",
                    f"nota_{self.g1.pk}_grupo": valor,
                },
            )
            self.assertIn(resp.status_code, (200, 302), f"nota={valor!r}")
            self.assertIsNone(GroupWorkDelivery.objects.get(group=self.g1).grade)

    def test_group_without_members_offers_nothing_to_register(self):
        vazio = self.make_work(title="Sem grupos")
        resp = self.client.get(
            reverse("pedagogy:group_work_deliveries", args=[vazio.pk])
        )
        self.assertContains(resp, "Nenhum grupo com integrantes")

    def test_work_grade_does_not_change_subject_average(self):
        """A nota do trabalho não entra na média da disciplina.

        Há uma avaliação real valendo 10 e uma nota de trabalho valendo 1: se
        a do trabalho contaminasse, a média deixaria de ser 10.
        """
        from apps.analytics import services

        from ..models import Evaluation, Grade

        ev = Evaluation.objects.create(
            school=self.school, subject=self.cie, class_group=self.turma,
            title="Prova", status=Evaluation.Status.PUBLISHED, created_by=self.prof,
        )
        Grade.objects.create(
            school=self.school, evaluation=ev, student=self.ana,
            value=Decimal("10.00"), updated_by=self.prof,
        )
        self.client.post(
            self.url,
            {
                f"status_{self.g1.pk}_grupo": "entregue",
                f"nota_{self.g1.pk}_grupo": "1,00",
            },
        )
        self.assertEqual(
            str(GroupWorkDelivery.objects.get(group=self.g1).grade), "1.00"
        )
        medias = services.subject_averages(self.ana)
        valores = [m["average"] for m in medias if m.get("average") is not None]
        self.assertTrue(valores, "esperava ao menos uma média")
        self.assertEqual(float(valores[0]), 10.0)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="escola-gw-media-"))
class AnexoTests(GroupWorkBase):
    def setUp(self):
        super().setUp()
        self.work = self.make_work()
        self.g1 = self.make_group(self.work, "Grupo 1", [self.ana])
        self.att = GroupWorkAttachment.objects.create(
            group_work=self.work,
            file=SimpleUploadedFile("roteiro.pdf", b"%PDF-1.4 x"),
            original_name="roteiro.pdf",
            size=10,
            uploaded_by=self.prof,
        )
        self.url = reverse(
            "pedagogy:group_work_attachment", args=[self.work.pk, self.att.pk]
        )

    def test_guardian_of_member_can_download(self):
        self.login("resp_ana")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp["Content-Disposition"].startswith("attachment"))

    def test_guardian_without_link_cannot_download(self):
        self.login("resp_zero")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_attachment_of_draft_is_blocked_for_family(self):
        self.work.status = GroupWork.Status.DRAFT
        self.work.save(update_fields=["status"])
        self.login("resp_ana")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_executable_attachment_is_rejected_on_create(self):
        self.login("prof")
        self.client.post(
            reverse("pedagogy:group_work_create"),
            dict(
                self.payload(title="Com executavel"),
                attachments=SimpleUploadedFile("x.pdf", b"MZ\x90\x00"),
            ),
        )
        self.assertFalse(GroupWork.objects.filter(title="Com executavel").exists())
