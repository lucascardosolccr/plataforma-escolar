"""Documentos da matrícula: lista da escola, entrega por turma ou por estudante, o que falta e o aviso às famílias."""

import datetime as dt

from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification
from apps.communication.tests.test_communication import CommunicationBase
from apps.core.models import AuditLog

from ..models import RequiredDocument, StudentDocument


class PaperworkTests(CommunicationBase):
    def setUp(self):
        super().setUp()
        self.year.is_current = True
        self.year.save()

    def docs(self):
        self.login("sec")
        self.client.get(reverse("paperwork:index"))
        return list(RequiredDocument.objects.filter(school=self.school))

    def test_class_sheet_saves_at_once_and_keeps_waivers(self):
        docs = self.docs()
        self.assertEqual(len(docs), len(RequiredDocument.DEFAULTS))
        page = self.client.get(reverse("paperwork:index") + f"?turma={self.turma.pk}")
        self.assertContains(page, "Ana")
        self.assertNotContains(page, "Beatriz")  # outra turma
        url = reverse("paperwork:save_class", args=[self.turma.pk])
        StudentDocument.objects.create(student=self.ana, document=docs[5], status="dispensado", on=timezone.localdate(),
                                       note="Primeira escola")
        self.client.post(url, {f"d_{self.ana.pk}_{docs[0].pk}": "on", f"d_{self.ana.pk}_{docs[1].pk}": "on"})
        self.assertEqual(set(StudentDocument.objects.values_list("document_id", "status")),
                         {(docs[0].pk, "entregue"), (docs[1].pk, "entregue"), (docs[5].pk, "dispensado")})
        self.client.post(url, {f"d_{self.ana.pk}_{docs[0].pk}": "on"})
        self.assertEqual(set(StudentDocument.objects.values_list("document_id", flat=True)), {docs[0].pk, docs[5].pk})
        self.assertTrue(AuditLog.objects.filter(detail__contains="Documentos da matrícula da turma").exists())

    def test_student_page_dates_waivers_and_undo(self):
        docs = self.docs()
        url = reverse("paperwork:student", args=[self.ana.pk])
        future = (timezone.localdate() + dt.timedelta(days=5)).isoformat()
        self.client.post(url, {"documento": docs[0].pk, "acao": "entregar", "em": future})
        self.client.post(url, {"documento": docs[1].pk, "acao": "entregar", "em": "2026-02-03"})
        self.client.post(url, {"documento": docs[2].pk, "acao": "dispensar"})  # sem motivo
        self.client.post(url, {"documento": docs[3].pk, "acao": "dispensar", "obs": "Mora com a avó"})
        got = {r.document_id: (r.status, r.on) for r in StudentDocument.objects.all()}
        self.assertEqual(got, {docs[0].pk: ("entregue", timezone.localdate()),
                               docs[1].pk: ("entregue", dt.date(2026, 2, 3)),
                               docs[3].pk: ("dispensado", timezone.localdate())})
        self.client.post(url, {"documento": docs[1].pk, "acao": "desfazer"})
        self.assertFalse(StudentDocument.objects.filter(document=docs[1]).exists())

    def test_family_sees_nothing_until_the_school_adopts_then_what_is_missing(self):
        self.docs()
        self.login("resp")
        self.assertContains(self.client.get(reverse("paperwork:index")), "ainda não acompanha")
        self.assertNotContains(self.client.get(reverse("pending_center")), "Documentos da matrícula a entregar")
        first = RequiredDocument.objects.filter(school=self.school).first()
        StudentDocument.objects.create(student=self.ana, document=first, on=timezone.localdate())
        page = self.client.get(reverse("paperwork:index"))
        self.assertContains(page, "falta entregar")
        self.assertContains(page, "entregue em")
        self.assertContains(self.client.get(reverse("pending_center")), "Documentos da matrícula a entregar")

    def test_access(self):
        self.docs()
        for user in ("prof", "coord", "resp"):
            self.login(user)
            self.assertEqual(self.client.get(reverse("paperwork:student", args=[self.ana.pk])).status_code, 403, user)
        for user in ("prof", "coord"):
            self.login(user)
            self.assertEqual(self.client.get(reverse("paperwork:index")).status_code, 403, user)
        self.client.force_login(self.other_prof)
        self.assertEqual(self.client.get(reverse("paperwork:index")).status_code, 403)
        self.login("dir")
        self.assertEqual(self.client.get(reverse("paperwork:student", args=[self.ana.pk])).status_code, 200)

    def test_remind_lists_what_is_missing_once_a_day_and_csv(self):
        docs = self.docs()
        StudentDocument.objects.create(student=self.ana, document=docs[0], on=timezone.localdate())
        self.client.post(reverse("paperwork:remind"), {"turma": self.turma.pk})
        self.client.post(reverse("paperwork:remind"), {"turma": self.turma.pk})
        note = Notification.objects.get(user=self.resp)
        self.assertIn("CPF do estudante", note.body)
        self.assertNotIn(docs[0].name, note.body)
        self.assertNotIn("Cartão do SUS", note.body)  # não obrigatório
        csv = self.client.get(reverse("paperwork:export")).content.decode("utf-8")
        self.assertIn("Ana", csv)
        self.assertIn("Beatriz", csv)

    def test_list_can_be_changed(self):
        docs = self.docs()
        self.client.post(reverse("paperwork:settings"), {"name": "Foto 3x4", "position": 9, "mandatory": "on",
                                                        "active": "on"})
        self.client.post(reverse("paperwork:settings_edit", args=[docs[6].pk]), {"name": docs[6].name, "position": 6})
        names = [d.name for d in RequiredDocument.objects.filter(school=self.school, active=True)]
        self.assertIn("Foto 3x4", names)
        self.assertNotIn(docs[6].name, names)
