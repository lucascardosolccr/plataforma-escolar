"""O que acontece com frequência, entregas e grupos depois da transferência.

Pendências da rodada anterior: a família perdia a frequência da turma
anterior, o professor não via quem tinha saído do grupo, e atividade ou
trabalho cancelado ainda aceitava lançamento de entrega.
"""

import time
from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification
from apps.core.middleware import ScheduledPublicationMiddleware
from apps.registry.models import Enrollment

from ..models import (
    Activity,
    AttendanceRecord,
    Evaluation,
    GroupWork,
    GroupWorkDelivery,
    Submission,
    WorkGroup,
    WorkGroupMember,
)
from .test_group_work import GroupWorkBase

SAIDA = date(2026, 5, 10)


class AfterTransferBase(GroupWorkBase):
    def transfer_ana(self):
        enr = Enrollment.objects.get(student=self.ana, class_group=self.turma)
        self.login("sec")
        resp = self.client.post(
            reverse("enrollment_transfer", args=[enr.pk]),
            {"class_group": self.turma_b.pk, "date": SAIDA.isoformat()},
        )
        self.assertRedirects(resp, reverse("enrollment_list"))
        self.client.logout()

    def activity(self, **extra):
        data = dict(
            school=self.school, class_group=self.turma, subject=self.cie,
            title="Leitura", description="Ler.", created_by=self.prof,
            status=Activity.Status.PUBLISHED, published_date=date(2026, 4, 1),
        )
        data.update(extra)
        return Activity.objects.create(**data)


class AttendanceAfterTransferTests(AfterTransferBase):
    def setUp(self):
        super().setUp()
        AttendanceRecord.objects.create(
            school=self.school, class_group=self.turma, student=self.ana,
            date=date(2026, 4, 2), status="falta",
        )
        AttendanceRecord.objects.create(
            school=self.school, class_group=self.turma, student=self.bruno,
            date=date(2026, 4, 2), status="presente",
        )
        self.transfer_ana()

    def test_family_lists_previous_class(self):
        for conta in ("resp_ana", "aluno_ana"):
            with self.subTest(conta=conta):
                self.login(conta)
                resp = self.client.get(reverse("pedagogy:attendance_list"))
                turmas = {c.pk for c in resp.context["classes"]}
                self.assertEqual(turmas, {self.turma.pk, self.turma_b.pk})
                self.assertContains(resp, "turma anterior", count=1)

    def test_family_sees_own_record_in_previous_class_only(self):
        for conta in ("resp_ana", "aluno_ana"):
            with self.subTest(conta=conta):
                self.login(conta)
                resp = self.client.get(
                    reverse("pedagogy:attendance_class", args=[self.turma.pk])
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual([s.pk for s in resp.context["students"]], [self.ana.pk])
                self.assertEqual(resp.context["summary"][self.ana.pk]["falta"], 1)
                self.assertNotContains(resp, "Bruno")
                # A marca de saída é só da equipe.
                self.assertNotContains(resp, "saiu da turma")

    def test_family_without_link_to_class_is_refused(self):
        self.login("resp_bruno")
        resp = self.client.get(
            reverse("pedagogy:attendance_class", args=[self.turma_b.pk])
        )
        self.assertEqual(resp.status_code, 403)

    def test_teacher_still_sees_record_of_who_left(self):
        self.login("prof")
        resp = self.client.get(
            reverse("pedagogy:attendance_class", args=[self.turma.pk])
        )
        nomes = [s.first_name for s in resp.context["students"]]
        self.assertEqual(nomes[-1], "Ana")
        self.assertContains(resp, "saiu da turma em 10/05/2026")
        # Só os ativos entram no lançamento de um novo dia.
        reg = self.client.get(
            reverse("pedagogy:attendance_register", args=[self.turma.pk])
        )
        self.assertNotIn(self.ana, list(reg.context["students"]))

    def test_staff_filter_by_student_lists_every_class(self):
        self.login("coord")
        resp = self.client.get(
            reverse("pedagogy:attendance_list") + f"?estudante={self.ana.pk}"
        )
        turmas = {c.pk for c in resp.context["classes"]}
        self.assertEqual(turmas, {self.turma.pk, self.turma_b.pk})


class SubmissionsAfterTransferTests(AfterTransferBase):
    def test_who_left_stays_in_the_list_with_mark(self):
        antes = self.activity(title="Antes")
        Submission.objects.create(
            school=self.school, activity=antes, student=self.ana,
            status="entregue", updated_by=self.prof,
        )
        depois = self.activity(title="Depois", published_date=date(2026, 6, 1))
        self.transfer_ana()
        self.login("prof")

        resp = self.client.get(reverse("pedagogy:activity_submissions", args=[antes.pk]))
        self.assertIn(self.ana.pk, [s.pk for s in resp.context["students"]])
        self.assertContains(resp, "saiu da turma em 10/05/2026")
        # O registro dela continua editável.
        self.client.post(
            reverse("pedagogy:activity_submissions", args=[antes.pk]),
            {f"status_{self.ana.pk}": "nao_entregue"},
        )
        self.assertEqual(
            Submission.objects.get(activity=antes, student=self.ana).status,
            "nao_entregue",
        )

        resp = self.client.get(reverse("pedagogy:activity_submissions", args=[depois.pk]))
        self.assertNotIn(self.ana.pk, [s.pk for s in resp.context["students"]])

    def test_canceled_activity_is_read_only(self):
        act = self.activity(status=Activity.Status.CANCELED, cancel_reason="Chuva")
        self.login("prof")
        url = reverse("pedagogy:activity_submissions", args=[act.pk])
        resp = self.client.get(url)
        self.assertContains(resp, "foi cancelada")
        self.assertContains(resp, "<fieldset disabled>", html=False)
        self.assertNotContains(resp, "Salvar entregas")
        resp = self.client.post(url, {f"status_{self.bruno.pk}": "entregue"})
        self.assertRedirects(resp, url)
        self.assertFalse(Submission.objects.filter(activity=act).exists())

    def test_staff_filter_by_student_follows_enrollment_period(self):
        self.activity(title="Antes da saida")
        self.activity(title="Depois da saida", published_date=date(2026, 6, 1))
        self.transfer_ana()
        self.login("coord")
        resp = self.client.get(
            reverse("pedagogy:activity_list") + f"?estudante={self.ana.pk}"
        )
        self.assertContains(resp, "Antes da saida")
        self.assertNotContains(resp, "Depois da saida")

    def test_staff_evaluation_filter_by_student_keeps_previous_class(self):
        def avaliacao(titulo, dia):
            return Evaluation.objects.create(
                school=self.school, subject=self.cie, class_group=self.turma,
                title=titulo, status="publicada", created_by=self.prof, date=dia,
            )

        avaliacao("Prova antes", date(2026, 4, 20))
        avaliacao("Prova depois", date(2026, 6, 20))
        self.transfer_ana()
        self.login("coord")
        resp = self.client.get(
            reverse("pedagogy:evaluation_list") + f"?estudante={self.ana.pk}"
        )
        self.assertContains(resp, "Prova antes")
        self.assertNotContains(resp, "Prova depois")


class GroupsAfterTransferTests(AfterTransferBase):
    def setUp(self):
        super().setUp()
        self.work = self.make_work()
        self.g1 = WorkGroup.objects.create(group_work=self.work, name="Grupo 1")
        for st in (self.ana, self.bruno):
            WorkGroupMember.objects.create(group=self.g1, student=st, added_by=self.prof)
        self.transfer_ana()
        self.url = reverse("pedagogy:group_work_groups", args=[self.work.pk])

    def test_teacher_sees_who_left(self):
        self.login("prof")
        resp = self.client.get(self.url)
        self.assertContains(resp, "saiu da turma em 10/05/2026")
        self.assertEqual([m.student for m in resp.context["left_members"]], [self.ana])
        detalhe = self.client.get(
            reverse("pedagogy:group_work_detail", args=[self.work.pk])
        )
        self.assertContains(detalhe, "saiu da turma")

    def test_family_of_classmate_does_not_learn_of_the_transfer(self):
        self.login("resp_bruno")
        resp = self.client.get(
            reverse("pedagogy:group_work_detail", args=[self.work.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ana")
        self.assertNotContains(resp, "saiu da turma")

    def atribuir(self, ana_value):
        data = {"_acao": "atribuir", f"grupo_{self.ana.pk}": ana_value}
        for st in (self.bruno, self.carla, self.davi):
            data[f"grupo_{st.pk}"] = str(self.g1.pk) if st == self.bruno else ""
        return self.client.post(self.url, data)

    def test_teacher_can_keep_or_remove_who_left(self):
        self.login("prof")
        self.atribuir(str(self.g1.pk))
        membro = WorkGroupMember.objects.get(group=self.g1, student=self.ana)
        self.assertIsNone(membro.removed_at)

        self.atribuir("")
        membro.refresh_from_db()
        self.assertIsNotNone(membro.removed_at)
        # Bruno não foi afetado, e Ana deixa de ser listada à parte.
        self.assertIsNone(
            WorkGroupMember.objects.get(group=self.g1, student=self.bruno).removed_at
        )
        resp = self.client.get(self.url)
        self.assertEqual(resp.context["left_members"], [])

    def test_who_left_cannot_be_moved_to_another_group(self):
        g2 = WorkGroup.objects.create(group_work=self.work, name="Grupo 2")
        self.login("prof")
        self.atribuir(str(g2.pk))
        self.assertFalse(
            WorkGroupMember.objects.filter(
                group=g2, student=self.ana, removed_at__isnull=True
            ).exists()
        )

    def test_deliveries_mark_who_left(self):
        self.work.delivery_mode = GroupWork.DeliveryMode.INDIVIDUAL
        self.work.save(update_fields=["delivery_mode"])
        self.login("prof")
        resp = self.client.get(
            reverse("pedagogy:group_work_deliveries", args=[self.work.pk])
        )
        self.assertContains(resp, "saiu da turma em 10/05/2026", count=1)


class CanceledGroupWorkDeliveriesTests(AfterTransferBase):
    def test_canceled_work_is_read_only(self):
        work = self.make_work(status=GroupWork.Status.CANCELED, cancel_reason="x")
        g = WorkGroup.objects.create(group_work=work, name="Grupo 1")
        WorkGroupMember.objects.create(group=g, student=self.bruno, added_by=self.prof)
        self.login("prof")
        url = reverse("pedagogy:group_work_deliveries", args=[work.pk])
        resp = self.client.get(url)
        self.assertContains(resp, "foi cancelado")
        self.assertNotContains(resp, "Salvar entregas")
        resp = self.client.post(url, {f"status_{g.pk}_grupo": "entregue"})
        self.assertRedirects(resp, url)
        self.assertFalse(GroupWorkDelivery.objects.filter(group_work=work).exists())


class NewDayDeliveryTests(AfterTransferBase):
    def test_first_request_of_a_new_day_delivers_without_waiting(self):
        hoje = timezone.localdate()
        act = self.activity(published_date=hoje)
        # Rodou há pouco, mas no dia anterior.
        ScheduledPublicationMiddleware._last_run = time.monotonic()
        ScheduledPublicationMiddleware._last_day = hoje - timedelta(days=1)
        self.login("coord")
        self.client.get(reverse("home"))
        act.refresh_from_db()
        self.assertIsNotNone(act.notified_at)
        self.assertTrue(
            Notification.objects.filter(user=self.resp_ana).exists()
        )
