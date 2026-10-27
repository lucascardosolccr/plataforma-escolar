"""Transferência de turma pelo fluxo real e avisos de publicação.

Os testes antigos simulavam a transferência mudando o status direto no banco.
O fluxo real (secretaria transfere pela tela) não existia: a regra de unicidade
impedia a segunda matrícula no ano, e a única saída era editar a turma da
matrícula — o que apagava o histórico da turma anterior. Estes testes passam
pelas telas.
"""

from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification
from apps.communication.services import announce_publication, deliver_due_publications
from apps.core.middleware import ScheduledPublicationMiddleware
from apps.core.models import AuditLog, Role
from apps.registry.models import Enrollment, GuardianLink, Student

from ..models import Activity, GroupWork, WorkGroup, WorkGroupMember
from .test_pedagogy import PedagogyBase, User


def _activity(base, **extra):
    data = dict(
        school=base.school,
        class_group=base.turma,
        subject=base.mat,
        title="Atividade",
        description="Instruções.",
        created_by=base.prof,
        status=Activity.Status.PUBLISHED,
        published_date=date(2026, 3, 1),
    )
    data.update(extra)
    return Activity.objects.create(**data)


class TransferFlowTests(PedagogyBase):
    TRANSFER = date(2026, 5, 10)

    def transfer_ana(self):
        enr = Enrollment.objects.get(student=self.ana, class_group=self.turma)
        self.login("sec")
        resp = self.client.post(
            reverse("enrollment_transfer", args=[enr.pk]),
            {"class_group": self.turma_b.pk, "date": self.TRANSFER.isoformat()},
        )
        self.assertRedirects(resp, reverse("enrollment_list"))
        self.client.logout()
        return enr

    def test_transfer_closes_old_and_opens_new_enrollment(self):
        old = self.transfer_ana()
        old.refresh_from_db()
        self.assertEqual(old.status, "transferido")
        self.assertEqual(old.ended_on, self.TRANSFER)
        new = Enrollment.objects.get(student=self.ana, status="ativo")
        self.assertEqual(new.class_group, self.turma_b)
        self.assertEqual(new.started_on, self.TRANSFER)
        self.assertTrue(
            AuditLog.objects.filter(detail__contains="Transferiu Ana").exists()
        )

    def test_family_keeps_history_but_not_what_came_after(self):
        antes = _activity(self, title="Antes da saida", published_date=date(2026, 4, 1))
        depois = _activity(self, title="Depois da saida", published_date=date(2026, 6, 1))
        vigente = _activity(
            self, class_group=self.turma_b, subject=self.port,
            title="Vigente na chegada", published_date=date(2026, 5, 1),
            deadline=date(2026, 5, 20),
        )
        vencida = _activity(
            self, class_group=self.turma_b, subject=self.port,
            title="Vencida antes da chegada", published_date=date(2026, 4, 1),
            deadline=date(2026, 4, 10),
        )
        self.transfer_ana()

        self.login("resp")
        lista = self.client.get(reverse("pedagogy:activity_list"))
        self.assertContains(lista, "Antes da saida")
        self.assertContains(lista, "Vigente na chegada")
        self.assertNotContains(lista, "Depois da saida")
        self.assertNotContains(lista, "Vencida antes da chegada")
        # Nem pelo identificador na URL.
        self.assertEqual(
            self.client.get(reverse("pedagogy:activity_detail", args=[depois.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("pedagogy:activity_detail", args=[antes.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("pedagogy:activity_detail", args=[vigente.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("pedagogy:activity_detail", args=[vencida.pk])).status_code,
            403,
        )

    def test_individual_record_matches_family_view(self):
        _activity(self, title="Antes da saida", published_date=date(2026, 4, 1))
        _activity(self, title="Depois da saida", published_date=date(2026, 6, 1))
        self.transfer_ana()
        self.login("coord")
        ficha = self.client.get(reverse("student_detail", args=[self.ana.pk]))
        self.assertContains(ficha, "Antes da saida")
        self.assertNotContains(ficha, "Depois da saida")

    def test_classmates_who_stayed_still_see_new_activities(self):
        """O recorte é por estudante: quem continua na turma não perde nada."""
        carla = Student.objects.create(school=self.school, first_name="Carla")
        Enrollment.objects.create(
            school=self.school, student=carla, class_group=self.turma, school_year=self.year
        )
        GuardianLink.objects.create(
            school=self.school, guardian=self.resp, student=carla, status="aprovado"
        )
        _activity(self, title="Depois da saida", published_date=date(2026, 6, 1))
        self.transfer_ana()
        self.login("resp")
        lista = self.client.get(reverse("pedagogy:activity_list"))
        self.assertContains(lista, "Depois da saida")
        linhas = [r for r in lista.context["rows"] if r["activity"].title == "Depois da saida"]
        self.assertEqual([r["student"] for r in linhas], [carla])

    def test_family_keeps_grades_from_previous_class(self):
        from ..models import Evaluation

        def avaliacao(titulo, turma, disciplina, dia):
            return Evaluation.objects.create(
                school=self.school, class_group=turma, subject=disciplina,
                title=titulo, date=dia, status=Evaluation.Status.PUBLISHED,
                created_by=self.prof,
            )

        avaliacao("Prova da turma antiga", self.turma, self.mat, date(2026, 4, 20))
        avaliacao("Prova depois da saida", self.turma, self.mat, date(2026, 6, 20))
        avaliacao("Prova da turma nova", self.turma_b, self.port, date(2026, 6, 20))
        avaliacao("Prova antes da chegada", self.turma_b, self.port, date(2026, 4, 20))
        self.transfer_ana()
        self.login("resp")
        lista = self.client.get(reverse("pedagogy:evaluation_list"))
        self.assertContains(lista, "Prova da turma antiga")
        self.assertContains(lista, "Prova da turma nova")
        self.assertNotContains(lista, "Prova depois da saida")
        self.assertNotContains(lista, "Prova antes da chegada")

    def test_cannot_transfer_to_same_class_or_inactive_enrollment(self):
        enr = Enrollment.objects.get(student=self.ana, class_group=self.turma)
        self.login("sec")
        resp = self.client.post(
            reverse("enrollment_transfer", args=[enr.pk]),
            {"class_group": self.turma.pk, "date": "2026-05-10"},
        )
        self.assertEqual(resp.status_code, 200)  # formulário com erro
        self.assertEqual(Enrollment.objects.filter(student=self.ana).count(), 1)
        enr.status = "concluido"
        enr.save()
        resp = self.client.post(
            reverse("enrollment_transfer", args=[enr.pk]),
            {"class_group": self.turma_b.pk, "date": "2026-05-10"},
        )
        self.assertRedirects(resp, reverse("enrollment_list"))
        self.assertEqual(Enrollment.objects.filter(student=self.ana).count(), 1)

    def test_only_registry_staff_can_transfer(self):
        enr = Enrollment.objects.get(student=self.ana, class_group=self.turma)
        for username in ("prof", "resp"):
            self.login(username)
            resp = self.client.post(
                reverse("enrollment_transfer", args=[enr.pk]),
                {"class_group": self.turma_b.pk, "date": "2026-05-10"},
            )
            self.assertEqual(resp.status_code, 403, username)
        self.assertEqual(Enrollment.objects.filter(student=self.ana).count(), 1)

    def test_edit_cannot_move_enrollment_to_another_class(self):
        enr = Enrollment.objects.get(student=self.ana, class_group=self.turma)
        self.login("sec")
        resp = self.client.post(
            reverse("enrollment_edit", args=[enr.pk]),
            {
                "student": self.ana.pk,
                "class_group": self.turma_b.pk,
                "school_year": self.year.pk,
                "status": "ativo",
            },
        )
        self.assertContains(resp, "Use “Transferir”")
        enr.refresh_from_db()
        self.assertEqual(enr.class_group, self.turma)

    def test_status_change_records_exit_date(self):
        enr = Enrollment.objects.get(student=self.ana, class_group=self.turma)
        self.login("sec")
        self.client.post(
            reverse("enrollment_edit", args=[enr.pk]),
            {
                "student": self.ana.pk,
                "class_group": self.turma.pk,
                "school_year": self.year.pk,
                "status": "desistente",
            },
        )
        enr.refresh_from_db()
        self.assertEqual(enr.ended_on, timezone.localdate())

    def test_second_active_enrollment_in_year_is_refused(self):
        self.login("sec")
        resp = self.client.post(
            reverse("enrollment_create"),
            {
                "student": self.ana.pk,
                "class_group": self.turma_b.pk,
                "school_year": self.year.pk,
                "status": "ativo",
            },
        )
        self.assertContains(resp, "já possui matrícula ativa")
        # E o banco também recusa, para além do formulário.
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.create(
                school=self.school, student=self.ana, class_group=self.turma_b,
                school_year=self.year, status="ativo",
            )

    def test_legacy_enrollment_without_dates_keeps_full_history(self):
        """Matrícula anterior a estes campos: nada some de quem já via."""
        Enrollment.objects.filter(student=self.ana).update(status="transferido")
        _activity(self, title="Qualquer data", published_date=date(2026, 9, 1))
        self.login("resp")
        self.assertContains(
            self.client.get(reverse("pedagogy:activity_list")), "Qualquer data"
        )


class PublicationNoticeTests(PedagogyBase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()

    def notices(self, user=None):
        return Notification.objects.filter(
            user=user or self.resp, kind=Notification.Kind.ACTIVITY
        )

    def post_activity(self, published_date, **extra):
        self.login("prof")
        data = {
            "class_group": self.turma.pk,
            "subject": self.mat.pk,
            "title": "Leitura dirigida",
            "description": "Ler as páginas 10 a 20.",
            "published_date": published_date.isoformat(),
            "_publish": "1",
        }
        data.update(extra)
        return self.client.post(reverse("pedagogy:activity_create"), data, follow=True)

    def test_scheduled_publication_waits_for_its_date(self):
        futura = self.today + timedelta(days=3)
        resp = self.post_activity(futura)
        self.assertContains(resp, "Publicação agendada")
        act = Activity.objects.get(title="Leitura dirigida")
        self.assertIsNone(act.notified_at)
        self.assertFalse(self.notices().exists())

        # O dia chega.
        Activity.objects.filter(pk=act.pk).update(published_date=self.today)
        self.assertEqual(deliver_due_publications(), 1)
        self.assertEqual(self.notices().count(), 1)
        # E o link do aviso abre para a família.
        self.login("resp")
        url = self.notices().get().url
        self.assertEqual(self.client.get(url).status_code, 200)

        # Rodar de novo não avisa em dobro.
        self.assertEqual(deliver_due_publications(), 0)
        self.assertEqual(self.notices().count(), 1)

    def test_immediate_publication_notifies_once_even_after_edits(self):
        self.post_activity(self.today)
        act = Activity.objects.get(title="Leitura dirigida")
        self.assertIsNotNone(act.notified_at)
        self.assertEqual(self.notices().count(), 1)
        self.client.post(
            reverse("pedagogy:activity_edit", args=[act.pk]),
            {
                "subject": self.mat.pk,
                "title": "Leitura dirigida (corrigida)",
                "description": "Ler as páginas 10 a 22.",
                "published_date": self.today.isoformat(),
            },
        )
        self.assertEqual(self.notices().count(), 1)
        self.assertFalse(announce_publication(act))

    def test_draft_is_never_announced(self):
        self.login("prof")
        self.client.post(
            reverse("pedagogy:activity_create"),
            {
                "class_group": self.turma.pk,
                "subject": self.mat.pk,
                "title": "Rascunho",
                "description": "Ainda não.",
                "published_date": self.today.isoformat(),
            },
        )
        self.assertEqual(deliver_due_publications(), 0)
        self.assertFalse(self.notices().exists())

    def test_middleware_delivers_due_publications(self):
        act = _activity(self, published_date=self.today, title="Agendada que venceu")
        self.assertIsNone(act.notified_at)
        ScheduledPublicationMiddleware._last_run = None
        self.login("coord")
        self.client.get(reverse("home"))
        self.assertEqual(self.notices().count(), 1)
        # Dentro do intervalo, não roda de novo.
        _activity(self, published_date=self.today, title="Outra")
        self.client.get(reverse("home"))
        self.assertEqual(self.notices().count(), 1)

    def test_cancel_notifies_who_was_notified(self):
        self.post_activity(self.today)
        act = Activity.objects.get(title="Leitura dirigida")
        self.client.post(
            reverse("pedagogy:activity_cancel", args=[act.pk]),
            {"cancel_reason": "Conteúdo remarcado"},
        )
        canceladas = self.notices().filter(title__startswith="Atividade cancelada")
        self.assertEqual(canceladas.count(), 1)
        self.assertIn("Conteúdo remarcado", canceladas.get().body)

    def test_cancel_of_unannounced_activity_is_silent(self):
        futura = self.today + timedelta(days=5)
        self.post_activity(futura)
        act = Activity.objects.get(title="Leitura dirigida")
        self.client.post(
            reverse("pedagogy:activity_cancel", args=[act.pk]),
            {"cancel_reason": "Desisti"},
        )
        self.assertFalse(self.notices().exists())
        # Cancelada não volta a ser avisada quando a data chegar.
        Activity.objects.filter(pk=act.pk).update(published_date=self.today)
        self.assertEqual(deliver_due_publications(), 0)

    def test_student_account_is_notified_too(self):
        conta = User.objects.create_user(
            username="ana.estudante", password="senha-forte-1",
            role=Role.ESTUDANTE, school=self.school,
        )
        self.ana.user = conta
        self.ana.save()
        self.post_activity(self.today)
        aviso = self.notices(conta).get()
        self.assertIn("Matemática", aviso.body)
        # O aviso do estudante não traz nome de ninguém.
        self.assertNotIn("Beatriz", aviso.body)

    def test_group_work_scheduled_is_delivered_later(self):
        work = GroupWork.objects.create(
            school=self.school, class_group=self.turma, subject=self.mat,
            title="Maquete", description="Construir a maquete.",
            created_by=self.prof, published_date=self.today + timedelta(days=2),
        )
        g = WorkGroup.objects.create(group_work=work, name="Grupo 1")
        WorkGroupMember.objects.create(group=g, student=self.ana)
        self.assertFalse(announce_publication(work))
        GroupWork.objects.filter(pk=work.pk).update(published_date=self.today)
        self.assertEqual(deliver_due_publications(), 1)
        self.assertTrue(
            self.notices().filter(title__startswith="Novo trabalho em grupo").exists()
        )


class PublishedActivityIntegrityTests(PedagogyBase):
    def setUp(self):
        super().setUp()
        # Professor com Matemática nas duas turmas, para a troca ser plausível.
        from apps.academics.models import TeacherAssignment

        TeacherAssignment.objects.create(
            school=self.school, school_year=self.year, teacher=self.prof,
            class_group=self.turma_b, subject=self.mat,
        )

    def edit(self, act, **extra):
        data = {
            "class_group": self.turma_b.pk,
            "subject": self.mat.pk,
            "title": "Editada",
            "description": "Novo texto.",
            "published_date": "2026-03-01",
        }
        data.update(extra)
        self.login("prof")
        return self.client.post(reverse("pedagogy:activity_edit", args=[act.pk]), data)

    def test_published_activity_keeps_its_class(self):
        act = _activity(self)
        self.edit(act)
        act.refresh_from_db()
        self.assertEqual(act.class_group, self.turma)
        self.assertEqual(act.title, "Editada")

    def test_draft_may_still_change_class(self):
        act = _activity(self, status=Activity.Status.DRAFT)
        self.edit(act)
        act.refresh_from_db()
        self.assertEqual(act.class_group, self.turma_b)

    def test_canceled_activity_is_not_editable(self):
        act = _activity(self, status=Activity.Status.CANCELED, cancel_reason="x")
        resp = self.edit(act)
        self.assertRedirects(resp, reverse("pedagogy:activity_detail", args=[act.pk]))
        act.refresh_from_db()
        self.assertEqual(act.title, "Atividade")
