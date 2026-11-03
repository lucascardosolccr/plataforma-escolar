"""Declarações de matrícula e de frequência emitidas pela secretaria."""

import datetime as dt

from django.urls import reverse

from apps.communication.models import Notification, ServiceRequest
from apps.communication.tests.test_communication import CommunicationBase
from apps.core.models import AuditLog
from apps.pedagogy.models import AttendanceRecord
from apps.registry.models import DocumentSettings, IssuedDocument, Student


class DocumentTests(CommunicationBase):
    def setUp(self):
        super().setUp()
        self.ana.last_name = "Souza"
        self.ana.birth_date = dt.date(2018, 5, 4)
        self.ana.save()
        self.url = reverse("document_new", args=[self.ana.pk])

    def test_enrollment_declaration_comes_from_the_records_with_number_and_code(self):
        self.login("sec")
        resp = self.client.post(self.url, {"kind": "matricula", "purpose": "Comprovação junto ao programa social"})
        doc = IssuedDocument.objects.get()
        self.assertRedirects(resp, reverse("document_print", args=[doc.pk]))
        self.assertIn("Ana Souza, nascido(a) em 04/05/2018,", doc.body)
        self.assertIn("ano letivo de 2026, na turma 1º Ano A", doc.body)
        self.assertIn("destina-se a comprovação junto ao programa social", doc.body)
        self.assertEqual(doc.number, f"0001/{dt.date.today().year}")
        self.assertRegex(doc.code, r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        self.client.post(self.url, {"kind": "matricula"})
        self.assertEqual(IssuedDocument.objects.order_by("-pk").first().sequence, 2)
        page = self.client.get(reverse("document_print", args=[doc.pk]))
        self.assertContains(page, doc.code)
        self.assertContains(page, "(cidade)")  # sem dados da escola: lacuna visível, nada inventado
        self.assertTrue(AuditLog.objects.filter(detail__startswith="Emitiu Declaração de matrícula").exists())

    def test_no_active_enrollment_no_declaration(self):
        caio = Student.objects.create(school=self.school, first_name="Caio")
        self.login("sec")
        resp = self.client.post(reverse("document_new", args=[caio.pk]), {"kind": "matricula"})
        self.assertContains(resp, "não tem matrícula ativa")
        self.assertFalse(IssuedDocument.objects.exists())

    def test_attendance_declaration_counts_the_period_and_refuses_without_records(self):
        for day, st in ((2, "presente"), (3, "falta"), (4, "atraso"), (5, "presente")):
            AttendanceRecord.objects.create(school=self.school, class_group=self.turma, student=self.ana,
                                            date=dt.date(2026, 3, day), status=st)
        self.login("sec")
        self.client.post(self.url, {"kind": "frequencia", "start": "2026-03-01", "end": "2026-03-31"})
        doc = IssuedDocument.objects.get()
        self.assertIn("presente em 75,0% dos 4 registros de chamada", doc.body)
        self.assertIn("01/03/2026 a 31/03/2026 (1 falta;", doc.body)
        resp = self.client.post(self.url, {"kind": "frequencia", "start": "2026-04-01", "end": "2026-04-30"})
        self.assertContains(resp, "Não há chamada registrada")
        self.assertEqual(IssuedDocument.objects.count(), 1)

    def test_request_from_family_is_answered(self):
        req = ServiceRequest.objects.create(school=self.school, requester=self.resp, student=self.ana,
                                            category="documento", title="Declaração de matrícula", description="Para o trabalho")
        self.login("sec")
        detail = self.client.get(reverse("communication:request_detail", args=[req.pk]))
        self.assertContains(detail, f"{self.url}?solicitacao={req.pk}")
        self.client.post(self.url, {"kind": "matricula", "solicitacao": req.pk})
        req.refresh_from_db()
        doc = IssuedDocument.objects.get()
        self.assertEqual((req.status, doc.request), ("respondida", req))
        self.assertIn(f"nº {doc.number}", req.response)
        self.assertTrue(Notification.objects.filter(user=self.resp, url__contains=f"/solicitacoes/{req.pk}/").exists())

    def test_settings_appear_on_the_document(self):
        DocumentSettings.objects.create(school=self.school, header="Rua das Flores, 10\nINEP 12345678",
                                        city="Brasília", signer_name="Maria Lima", signer_role="Secretária escolar")
        self.login("sec")
        self.client.post(self.url, {"kind": "matricula"})
        page = self.client.get(reverse("document_print", args=[IssuedDocument.objects.get().pk]))
        for text in ("INEP 12345678", "Brasília, ", "Maria Lima", "Secretária escolar"):
            self.assertContains(page, text)
        self.assertNotContains(page, "(cidade)")

    def test_who_can_issue_and_verification_by_code(self):
        for user, code in (("prof", 403), ("resp", 403), ("coord", 403), ("dir", 200), ("adm", 200)):
            self.login(user)
            self.assertEqual(self.client.get(self.url).status_code, code, user)
        self.login("sec")
        self.client.post(self.url, {"kind": "matricula"})
        doc = IssuedDocument.objects.get()
        ok = self.client.get(reverse("document_list") + f"?codigo={doc.code.replace('-', '').lower()}")
        self.assertContains(ok, "Declaração válida")
        self.assertContains(self.client.get(reverse("document_list") + "?codigo=ZZZZ-ZZZZ"), "Nenhuma declaração com este código")
        self.login("resp_b")  # outra escola
        self.assertEqual(self.client.get(reverse("document_print", args=[doc.pk])).status_code, 403)
