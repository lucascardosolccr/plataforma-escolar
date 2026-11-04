"""Pedidos do titular sobre dados pessoais (LGPD, art. 18 e 19) e inventário do que a plataforma guarda."""

import datetime as dt

from django.urls import reverse
from django.utils import timezone
from django.utils.text import camel_case_to_spaces

from apps.core.models import AuditLog
from apps.registry.models import Student

from ..models import Notification, ServiceRequest
from .test_communication import CommunicationBase


class LgpdRequestTests(CommunicationBase):
    def _ask(self, **extra):
        self.client.force_login(self.resp)
        data = {"student": self.ana.pk, "category": "lgpd", "data_right": "acesso", "title": "Cópia dos dados",
                "description": "Quero saber o que a escola guarda sobre a Ana."}
        data.update(extra)
        return self.client.post(reverse("communication:request_create"), data)

    def test_family_asks_with_the_right_and_school_gets_the_deadline(self):
        self._ask()
        req = ServiceRequest.objects.get()
        self.assertEqual((req.category, req.data_right), ("lgpd", "acesso"))
        self.assertEqual(req.due_on, timezone.localdate() + dt.timedelta(days=15))
        for who in (self.sec, self.direc):
            self.assertTrue(Notification.objects.filter(user=who, title__contains="dados pessoais (LGPD)").exists())
        self.assertFalse(Notification.objects.filter(user=self.coord).exists())
        # Sem o direito escolhido, a categoria LGPD não passa; escolher o direito já põe na categoria.
        self._ask(data_right="", title="Sem direito")
        self.assertFalse(ServiceRequest.objects.filter(title="Sem direito").exists())
        self._ask(category="outro", data_right="correcao", title="Corrigir nascimento")
        self.assertEqual(ServiceRequest.objects.get(title="Corrigir nascimento").category, "lgpd")

    def test_teacher_and_coordination_never_see_the_request(self):
        self._ask()
        req = ServiceRequest.objects.get()
        detail = reverse("communication:request_detail", args=[req.pk])
        for user in (self.prof, self.coord):
            self.client.force_login(user)
            self.assertNotContains(self.client.get(reverse("communication:request_list")), "Cópia dos dados")
            self.assertEqual(self.client.get(detail).status_code, 403, user.username)
        self.client.force_login(self.sec)
        page = self.client.get(detail)
        self.assertContains(page, "Receber os dados que a escola guarda")
        self.assertNotContains(page, "O que a plataforma guarda sobre o estudante")  # inventário é da direção
        self.client.post(detail, {"status": "respondida", "response": "Enviamos a cópia impressa."})
        self.assertTrue(Notification.objects.filter(user=self.resp).exists())  # família avisada da resposta

    def test_pending_center_counts_overdue_requests(self):
        self._ask()
        ServiceRequest.objects.update(created_at=timezone.now() - dt.timedelta(days=20))
        self.client.force_login(self.direc)
        page = self.client.get(reverse("pending_center"))
        self.assertContains(page, "Pedidos sobre dados pessoais (LGPD)")
        self.assertContains(page, "1 com prazo vencido")
        ServiceRequest.objects.update(status="respondida")
        self.assertNotContains(self.client.get(reverse("pending_center")), "Pedidos sobre dados pessoais")


class DataInventoryTests(CommunicationBase):
    def test_only_management_opens_it_and_every_student_record_has_a_portuguese_name(self):
        url = reverse("student_data_inventory", args=[self.ana.pk])
        for user in (self.sec, self.admin, self.coord, self.prof, self.resp):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403, user.username)
        self.client.force_login(self.direc)
        page = self.client.get(url)
        self.assertContains(page, "Matrículas")
        self.assertTrue(AuditLog.objects.filter(detail__startswith="Consultou o inventário de dados pessoais").exists())
        # Toda tabela ligada ao estudante aparece no inventário pelo nome em português, nunca pelo nome que o
        # Django deriva da classe ("rubric score"). Modelo novo ligado ao estudante precisa de verbose_name.
        for rel in Student._meta.related_objects:
            meta = rel.related_model._meta
            self.assertNotEqual(str(meta.verbose_name), camel_case_to_spaces(meta.object_name), meta.label)

    def test_inventory_names_the_external_host_and_the_international_transfer(self):
        self.client.force_login(self.direc)
        url = reverse("student_data_inventory", args=[self.ana.pk])
        self.assertContains(self.client.get(url), "funciona no servidor da escola")
        with self.settings(HOSTING_PROVIDER="PythonAnywhere, com servidores na União Europeia"):
            page = self.client.get(url)
        self.assertContains(page, "Hospedagem: PythonAnywhere")
        self.assertContains(page, "transferência internacional (art. 33)")
        self.assertNotContains(page, "funciona no servidor da escola")

    def test_family_profile_offers_the_request(self):
        self.client.force_login(self.resp)
        page = self.client.get(reverse("guardian_profile", args=[self.resp.pk]))
        self.assertContains(page, "?categoria=lgpd")
        form = self.client.get(reverse("communication:request_create") + "?categoria=lgpd").context["form"]
        self.assertEqual(form.initial["category"], "lgpd")


class RequestResolutionTests(CommunicationBase):
    def test_invalid_resolution_shows_what_is_saved_not_the_rejected_text(self):
        req = ServiceRequest.objects.create(school=self.school, requester=self.resp, student=self.ana,
                                            title="Atestado", description="x")
        self.client.force_login(self.sec)
        page = self.client.post(reverse("communication:request_detail", args=[req.pk]),
                                {"status": "situacao-inexistente", "response": "Texto que não foi salvo"})
        self.assertEqual(page.status_code, 200)  # antes: erro 500
        self.assertNotContains(page, "Resposta da equipe</h3>")
        req.refresh_from_db()
        self.assertEqual((req.status, req.response), ("recebida", ""))
