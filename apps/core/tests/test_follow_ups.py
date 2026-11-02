"""Pendências acompanhadas: responsável, prazo, situação e histórico (Prompt 15 §6.4)."""

import datetime as dt

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification
from apps.communication.tests.test_communication import CommunicationBase
from apps.core.models import FollowUp, Role

User = get_user_model()


class FollowUpTests(CommunicationBase):
    def setUp(self):
        super().setUp()
        self.prof2 = User.objects.create_user(username="prof2", password="senha-forte-1", role=Role.PROFESSOR,
                                              school=self.school)

    def _create(self, **extra):
        data = {"title": "Conferir as notas do 1º bimestre", "category": "avaliacoes", "assignee": self.prof.pk,
                "due_date": (timezone.localdate() + dt.timedelta(days=3)).isoformat(), "description": "", "link": ""}
        data.update(extra)
        return self.client.post(reverse("follow_up_create"), data)

    def test_secretaria_assigns_teacher_who_is_notified_and_sees_it_in_the_center(self):
        self.login("sec")
        self._create(student=self.ana.pk, link="/pendencias/")
        fu = FollowUp.objects.get()
        self.assertEqual((fu.assignee, fu.created_by, fu.status, fu.link), (self.prof, self.sec, "aberta", "/pendencias/"))
        self.assertEqual(fu.events.count(), 1)
        self.assertTrue(Notification.objects.filter(user=self.prof, url=reverse("follow_up_detail", args=[fu.pk])).exists())
        self.login("prof")
        center = self.client.get(reverse("pending_center"))
        self.assertContains(center, "Pendências atribuídas a você")
        # Itens pessoais (a própria foto) e o próprio resumo não oferecem "Atribuir".
        self.assertNotContains(center, "?titulo=Sua%20foto")
        self.assertNotContains(center, "?titulo=Pend%C3%AAncias%20atribu")
        self.assertContains(self.client.get(reverse("follow_up_list")), "Conferir as notas do 1º bimestre")

    def test_status_reassignment_and_due_date_go_to_history(self):
        self.login("sec")
        self._create()
        fu = FollowUp.objects.get()
        self.login("prof")
        url = reverse("follow_up_detail", args=[fu.pk])
        self.client.post(url, {"status": "andamento", "assignee": self.prof.pk, "due_date": fu.due_date.isoformat(),
                               "note": "Comecei hoje."})
        self.client.post(url, {"status": "andamento", "assignee": self.prof2.pk, "due_date": "", "note": ""})
        self.client.post(url, {"status": "resolvida", "assignee": self.prof2.pk, "due_date": "", "note": ""})  # prof já não é responsável nem autor
        fu.refresh_from_db()
        self.assertEqual((fu.status, fu.assignee, fu.due_date), ("andamento", self.prof2, None))
        changes = list(fu.events.values_list("change", flat=True))
        self.assertEqual(len(changes), 3)
        self.assertIn("Situação: Aberta → Em andamento", changes[1])
        self.assertIn("Responsável:", changes[2])
        self.assertIn("Prazo:", changes[2])
        self.assertTrue(Notification.objects.filter(user=self.prof2).exists())
        self.login("prof2")
        self.client.post(url, {"status": "resolvida", "assignee": self.prof2.pk, "due_date": "", "note": "Feito."})
        fu.refresh_from_db()
        self.assertEqual(fu.status, "resolvida")
        self.assertIsNotNone(fu.closed_at)

    def test_cancel_requires_reason(self):
        self.login("sec")
        self._create()
        fu = FollowUp.objects.get()
        self.client.post(reverse("follow_up_detail", args=[fu.pk]),
                         {"status": "cancelada", "assignee": self.prof.pk, "due_date": "", "note": ""})
        fu.refresh_from_db()
        self.assertEqual(fu.status, "aberta")

    def test_overdue_shows_in_center_hint(self):
        self.login("sec")
        self._create(due_date=(timezone.localdate() - dt.timedelta(days=1)).isoformat())
        self.login("prof")
        self.assertContains(self.client.get(reverse("pending_center")), "1 com prazo vencido")
        self.assertContains(self.client.get(reverse("follow_up_list") + "?situacao=atrasadas"), "atrasada")

    def test_student_must_be_visible_to_assignee(self):
        # Beatriz é do 1º Ano B; o professor só leciona no 1º Ano A.
        self.login("sec")
        resp = self._create(student=self.bea.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(FollowUp.objects.exists())

    def test_link_must_be_internal(self):
        self.login("sec")
        self._create(link="https://exemplo.com/x")
        self.assertFalse(FollowUp.objects.exists())

    def test_follow_up_visibility(self):
        self.login("sec")
        self._create()
        fu = FollowUp.objects.get()
        url = reverse("follow_up_detail", args=[fu.pk])
        self.login("prof2")  # mesma escola, sem relação com a pendência
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertNotContains(self.client.get(reverse("follow_up_list") + "?escopo="), fu.title)
        self.login("dir")  # direção vê todas da escola
        self.assertEqual(self.client.get(url).status_code, 200)
        self.login("resp")  # família nunca
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(reverse("follow_up_list")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("pending_center")), "Pendências acompanhadas")
        self.login("prof_b")  # outra escola
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_center_items_offer_assignment_with_prefilled_link(self):
        self.login("sec")
        page = self.client.get(reverse("follow_up_create") + "?titulo=Chamadas%20sem%20registro&tela=/pendencias/")
        self.assertContains(page, 'value="Chamadas sem registro"')
        self.assertContains(page, 'value="/pendencias/"')
