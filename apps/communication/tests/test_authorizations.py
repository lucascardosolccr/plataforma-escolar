"""Autorizações de passeio respondidas pela família na plataforma."""

import datetime as dt

from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditLog
from apps.registry.models import GuardianLink

from ..models import Authorization, AuthorizationResponse, Notification
from .test_communication import CommunicationBase


class AuthorizationTests(CommunicationBase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        # Beatriz (1º Ano B) também tem responsável, para conferir que só a turma escolhida recebe.
        from django.contrib.auth import get_user_model

        from apps.core.models import Role

        self.resp_bea = get_user_model().objects.create_user("resp_bea", password="senha-forte-1",
                                                             role=Role.RESPONSAVEL, school=self.school)
        GuardianLink.objects.create(school=self.school, guardian=self.resp_bea, student=self.bea, status="aprovado")

    def _create(self, user="prof", **extra):
        self.login(user)
        data = {"title": "Passeio ao Zoológico", "description": "Saída 8h, volta 12h. Levar lanche.",
                "event_date": (self.today + dt.timedelta(days=10)).isoformat(),
                "deadline": (self.today + dt.timedelta(days=5)).isoformat(), "class_groups": [self.turma.pk]}
        data.update(extra)
        self.client.post(reverse("communication:authorization_create"), data)
        return Authorization.objects.filter(title=data["title"]).first()

    def _answer(self, auth, answer="autorizo", student=None, note=""):
        return self.client.post(reverse("communication:authorization_answer", args=[auth.pk]),
                                {"student": (student or self.ana).pk, "answer": answer, "note": note})

    def test_teacher_creates_for_own_class_and_only_those_families_are_notified(self):
        auth = self._create()
        self.assertIsNotNone(auth)
        self.assertTrue(Notification.objects.filter(user=self.resp, title__startswith="Autorização:").exists())
        self.assertFalse(Notification.objects.filter(user=self.resp_bea, title__startswith="Autorização:").exists())
        self.assertIsNone(self._create(title="Outra turma", class_groups=[self.turma_b.pk]))  # não leciona lá

    def test_family_answers_changes_and_staff_sees_counts_and_printable_list(self):
        auth = self._create()
        self.login("resp")
        self.assertContains(self.client.get(reverse("pending_center")), "Autorizações de passeio aguardando")
        self._answer(auth, "nao_autorizo")
        self._answer(auth, "autorizo", note="Alérgica a amendoim")  # muda até o prazo
        resp = AuthorizationResponse.objects.get()
        self.assertEqual((resp.answer, resp.note, resp.answered_by), ("autorizo", "Alérgica a amendoim", self.resp))
        self.assertEqual(AuditLog.objects.filter(target_type="AuthorizationResponse").count(), 2)
        self.assertNotContains(self.client.get(reverse("pending_center")), "Autorizações de passeio aguardando")
        self.login("prof")
        detail = self.client.get(reverse("communication:authorization_detail", args=[auth.pk]))
        self.assertContains(detail, "1 autoriza<")
        printed = self.client.get(reverse("communication:authorization_detail", args=[auth.pk]) + "?imprimir=1")
        self.assertContains(printed, "Ana")
        self.assertContains(printed, "Alérgica a amendoim")

    def test_refusals(self):
        auth = self._create()
        self.login("resp")
        self._answer(auth, student=self.bea)  # não é filho dele
        self.assertFalse(AuthorizationResponse.objects.exists())
        self.login("resp_bea")  # filha em outra turma: não vê nem responde
        self.assertEqual(self.client.get(reverse("communication:authorization_detail", args=[auth.pk])).status_code, 404)
        self._answer(auth, student=self.bea)
        self.assertFalse(AuthorizationResponse.objects.exists())
        self.login("resp_b")  # outra escola
        self.assertEqual(self.client.post(reverse("communication:authorization_answer", args=[auth.pk]),
                                          {"student": self.ana.pk, "answer": "autorizo"}).status_code, 404)
        Authorization.objects.filter(pk=auth.pk).update(deadline=self.today - dt.timedelta(days=1))
        self.login("resp")
        self._answer(auth)
        self.assertFalse(AuthorizationResponse.objects.exists())  # prazo vencido

    def test_cancel_needs_reason_and_notifies(self):
        auth = self._create()
        url = reverse("communication:authorization_status", args=[auth.pk, "cancelar"])
        self.client.post(url, {"reason": ""})
        auth.refresh_from_db()
        self.assertEqual(auth.status, "aberta")
        self.client.post(url, {"reason": "Previsão de chuva forte"})
        auth.refresh_from_db()
        self.assertEqual((auth.status, auth.cancel_reason), ("cancelada", "Previsão de chuva forte"))
        self.assertTrue(Notification.objects.filter(user=self.resp, title__startswith="Cancelada:").exists())
        self.login("sec")  # não criou e não é direção: não cancela
        auth2 = self._create(user="prof", title="Teatro")
        self.login("sec")
        self.assertEqual(self.client.post(reverse("communication:authorization_status", args=[auth2.pk, "cancelar"]),
                                          {"reason": "x"}).status_code, 403)
