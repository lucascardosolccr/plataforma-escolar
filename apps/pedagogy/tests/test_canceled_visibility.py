"""O que a família vê depois de um cancelamento.

O cancelamento preserva o histórico: quem já via a atividade continua vendo,
agora com o motivo. Mas cancelar um RASCUNHO (ou uma publicação agendada que
ainda não chegou) não pode transformá-lo em algo visível — a família nunca
deveria saber que ele existiu. Antes, as listas filtravam apenas
``exclude(status=DRAFT)`` e o rascunho cancelado aparecia para a família, na
ficha do estudante e no calendário.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from ..models import Activity, GroupWork
from .test_group_work import GroupWorkBase
from .test_pedagogy import PedagogyBase


class ActivityCancelVisibilityTests(PedagogyBase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()

    def _make(self, status, **extra):
        data = dict(
            school=self.school,
            class_group=self.turma,
            subject=self.mat,
            title=extra.pop("title", "Atividade"),
            description="Instruções.",
            created_by=self.prof,
            status=status,
            published_date=self.today - timedelta(days=3),
        )
        data.update(extra)
        return Activity.objects.create(**data)

    def _cancel(self, act):
        self.login("prof")
        resp = self.client.post(
            reverse("pedagogy:activity_cancel", args=[act.pk]),
            {"cancel_reason": "Turma em passeio"},
        )
        self.assertEqual(resp.status_code, 302)
        act.refresh_from_db()
        self.assertEqual(act.status, Activity.Status.CANCELED)
        self.client.logout()
        return act

    def test_canceled_draft_stays_hidden_from_family(self):
        act = self._cancel(
            self._make(Activity.Status.DRAFT, title="Rascunho que nunca saiu")
        )
        self.assertFalse(act.is_visible_to_family)
        self.login("resp")
        lista = self.client.get(reverse("pedagogy:activity_list"))
        self.assertNotContains(lista, "Rascunho que nunca saiu")
        detalhe = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        self.assertEqual(detalhe.status_code, 403)

    def test_canceled_draft_not_in_student_record(self):
        act = self._cancel(
            self._make(Activity.Status.DRAFT, title="Rascunho que nunca saiu")
        )
        from ..views import student_activity_rows

        self.assertNotIn(act, [r["activity"] for r in student_activity_rows(self.ana)])

    def test_canceled_draft_not_in_family_calendar(self):
        self._cancel(self._make(Activity.Status.DRAFT, title="Rascunho que nunca saiu"))
        self.login("resp")
        resp = self.client.get(reverse("school_calendar:calendar_index"))
        self.assertNotContains(resp, "Rascunho que nunca saiu")

    def test_canceled_scheduled_never_reaches_family(self):
        """Agendada e cancelada antes da data: a família nunca a viu."""
        act = self._make(
            Activity.Status.PUBLISHED,
            title="Agendada e desistida",
            published_date=self.today + timedelta(days=2),
        )
        act = self._cancel(act)
        self.assertFalse(act.visible_before_cancel)
        # Mesmo depois que a data chega, continua fora.
        Activity.objects.filter(pk=act.pk).update(
            published_date=self.today - timedelta(days=1)
        )
        act.refresh_from_db()
        self.assertFalse(act.is_visible_to_family)

    def test_canceled_published_keeps_history_with_reason(self):
        act = self._cancel(
            self._make(Activity.Status.PUBLISHED, title="Pesquisa sobre rios")
        )
        self.assertTrue(act.visible_before_cancel)
        self.login("resp")
        lista = self.client.get(reverse("pedagogy:activity_list"))
        self.assertContains(lista, "Pesquisa sobre rios")
        self.assertContains(lista, "Turma em passeio")
        detalhe = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        self.assertEqual(detalhe.status_code, 200)
        self.assertContains(detalhe, "Atividade cancelada")

    def test_staff_still_sees_canceled_draft(self):
        """Para a equipe nada some: a atividade continua auditável."""
        act = self._cancel(
            self._make(Activity.Status.DRAFT, title="Rascunho que nunca saiu")
        )
        self.login("prof")
        resp = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(reverse("pedagogy:activity_list"))
        self.assertContains(resp, "Rascunho que nunca saiu")


class GroupWorkCancelVisibilityTests(GroupWorkBase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()

    def _cancel(self, work):
        self.login("prof")
        self.client.post(
            reverse("pedagogy:group_work_cancel", args=[work.pk]),
            {"cancel_reason": "Mudança de planejamento"},
        )
        work.refresh_from_db()
        self.assertEqual(work.status, GroupWork.Status.CANCELED)
        self.client.logout()
        return work

    def test_canceled_draft_group_work_hidden_from_family(self):
        work = self.make_work(
            status=GroupWork.Status.DRAFT,
            title="Rascunho de grupo",
            published_date=self.today - timedelta(days=3),
        )
        self.make_group(work, "Grupo 1", [self.ana, self.bruno])
        work = self._cancel(work)
        self.assertFalse(work.is_visible_to_family)
        self.login("resp_ana")
        lista = self.client.get(reverse("pedagogy:group_work_list"))
        self.assertNotContains(lista, "Rascunho de grupo")
        detalhe = self.client.get(reverse("pedagogy:group_work_detail", args=[work.pk]))
        self.assertEqual(detalhe.status_code, 403)
        from ..views import student_group_work_rows

        self.assertEqual(student_group_work_rows(self.ana), [])

    def test_canceled_published_group_work_keeps_history(self):
        work = self.make_work(
            title="Maquete do bairro",
            published_date=self.today - timedelta(days=3),
        )
        self.make_group(work, "Grupo 1", [self.ana, self.bruno])
        work = self._cancel(work)
        self.assertTrue(work.visible_before_cancel)
        self.login("resp_ana")
        lista = self.client.get(reverse("pedagogy:group_work_list"))
        self.assertContains(lista, "Maquete do bairro")
