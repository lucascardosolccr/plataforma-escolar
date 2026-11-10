"""Confirmação de rematrícula: campanha, aviso, resposta da família com selo, balcão, lembretes, painel e lote."""

import datetime as dt
import re
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear
from apps.communication.models import Notification
from apps.communication.tests.test_communication import CommunicationBase
from apps.core.models import AuditLog
from apps.registry.models import Enrollment

from ..models import Answer, Campaign
from ..services import daily, intact, pending_for_family

TODAY = timezone.localdate()


class ReenrollTests(CommunicationBase):
    def setUp(self):
        super().setUp()
        self.year.is_current = True
        self.year.save()
        self.next = SchoolYear.objects.create(school=self.school, name="2027")

    def open_campaign(self, **extra):
        self.login("sec")
        data = {"title": "Rematrícula 2027", "target_year": self.next.pk, "opens_on": TODAY.isoformat(),
                "deadline": (TODAY + dt.timedelta(days=10)).isoformat(), "message": "Traga o comprovante.", **extra}
        resp = self.client.post(reverse("reenroll:create"), data)
        self.assertEqual(resp.status_code, 302, getattr(resp, "context", {}) and resp.context["form"].errors)
        return Campaign.objects.order_by("-pk").first()

    def answer(self, c, student=None, **data):
        self.login("resp")
        payload = {"estudante": (student or self.ana).pk, "decision": "continua", "data_ok": "on", **data}
        return self.client.post(reverse("reenroll:answer", args=[c.pk]) + f"?estudante={payload['estudante']}",
                                payload)

    def test_opening_notifies_families_and_only_managers_open(self):
        self.login("coord")
        self.assertEqual(self.client.get(reverse("reenroll:create")).status_code, 403)
        c = self.open_campaign()
        self.assertIsNotNone(c.announced_at)
        note = Notification.objects.get(user=self.resp, title__contains="Rematrícula 2027")
        self.assertEqual((note.priority, note.student), ("importante", self.ana))
        self.login("coord")  # acompanha
        self.assertEqual(self.client.get(reverse("reenroll:detail", args=[c.pk])).status_code, 200)
        self.login("resp")
        self.assertContains(self.client.get(reverse("pending_center")), "Rematrícula: diga se o estudante continua")

    def test_family_answers_with_seal_and_can_change_until_deadline(self):
        c = self.open_campaign()
        self.answer(c)
        a = Answer.objects.get()
        self.assertEqual((a.decision, a.answered_by, a.in_person), ("continua", self.resp, False))
        self.assertTrue(intact(a))
        self.assertEqual(pending_for_family(self.resp), 0)
        page = self.client.get(reverse("reenroll:index"))
        self.assertRegex(page.content.decode(), r"comprovante <code>[0-9A-Z]{5}-[0-9A-Z]{5}</code>")
        self.answer(c, decision="sai")  # sem motivo: não muda
        a.refresh_from_db()
        self.assertEqual(a.decision, "continua")
        self.answer(c, decision="sai", reason="mudanca", reason_text="Vamos para Curitiba")
        a.refresh_from_db()
        self.assertEqual((a.decision, a.reason), ("sai", "mudanca"))
        self.assertTrue(AuditLog.objects.filter(detail__contains="mudou de “Vai continuar” para").exists())
        with mock.patch("django.utils.timezone.localdate", return_value=TODAY + dt.timedelta(days=11)):
            self.answer(c, decision="continua")
        a.refresh_from_db()
        self.assertEqual(a.decision, "sai")  # prazo terminou

    def test_validation_data_check_and_terms(self):
        c = self.open_campaign(terms="Concordo com o regimento 2027.")
        self.answer(c, data_ok="")
        self.assertFalse(Answer.objects.exists())  # nem dados certos nem mudança
        self.answer(c, data_ok="", data_changes="Telefone novo: 99999-0000")
        self.assertFalse(Answer.objects.exists())  # faltou o termo
        self.answer(c, data_ok="", data_changes="Telefone novo: 99999-0000", accept="on")
        a = Answer.objects.get()
        self.assertTrue(a.accepted_terms)
        self.assertEqual(a.data_changes, "Telefone novo: 99999-0000")
        self.answer(c, decision="sai", reason="custo")  # quem sai não precisa do termo
        a.refresh_from_db()
        self.assertEqual((a.decision, a.accepted_terms, a.data_changes), ("sai", False, ""))

    def test_permissions(self):
        c = self.open_campaign()
        self.login("resp")
        url = reverse("reenroll:answer", args=[c.pk])
        self.assertEqual(self.client.get(url + f"?estudante={self.bea.pk}").status_code, 404)  # não é filho
        self.login("resp_b")
        self.assertIn(self.client.get(url + f"?estudante={self.ana.pk}").status_code, (403, 404))
        self.login("prof")
        self.assertEqual(self.client.get(reverse("reenroll:detail", args=[c.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("reenroll:export", args=[c.pk])).status_code, 403)

    def test_panel_counter_in_person_data_done_and_export(self):
        c = self.open_campaign()
        self.answer(c, data_ok="", data_changes="=HYPERLINK(\"x\") endereço novo")
        self.login("sec")
        page = self.client.get(reverse("reenroll:detail", args=[c.pk]))
        self.assertEqual(page.context["stats"]["continua"], 1)
        self.assertEqual(page.context["stats"]["pendente"], 1)  # Beatriz
        self.assertContains(self.client.get(reverse("pending_center")), "cadastros a atualizar")
        # Beatriz não tem responsável com conta: a secretaria registra no balcão
        url = reverse("reenroll:in_person", args=[c.pk, self.bea.pk])
        self.client.post(url, {"decision": "sai", "reason": "transferencia"})
        self.assertFalse(Answer.objects.filter(student=self.bea).exists())  # faltou quem respondeu
        self.client.post(url, {"decision": "sai", "reason": "transferencia", "on_behalf": "Mãe da Beatriz"})
        bea = Answer.objects.get(student=self.bea)
        self.assertEqual((bea.in_person, bea.answered_by_name, bea.answered_by), (True, "Mãe da Beatriz", self.sec))
        ana = Answer.objects.get(student=self.ana)
        self.client.post(reverse("reenroll:data_done", args=[ana.pk]))
        ana.refresh_from_db()
        self.assertTrue(ana.data_done and intact(ana))
        csv = self.client.get(reverse("reenroll:export", args=[c.pk])).content.decode("utf-8-sig")
        self.assertIn("Mãe da Beatriz", csv)
        self.assertIn("'=HYPERLINK", csv)  # fórmula neutralizada
        self.assertIn("Vai estudar em outra escola", csv)

    def test_tampering_is_flagged(self):
        c = self.open_campaign()
        self.answer(c, decision="sai", reason="custo")
        Answer.objects.update(decision="continua")  # mudança direto no banco
        self.login("sec")
        self.assertContains(self.client.get(reverse("reenroll:detail", args=[c.pk])), "registro alterado fora")

    def test_daily_announces_on_opening_and_reminds_only_pending(self):
        c = self.open_campaign(opens_on=(TODAY + dt.timedelta(days=2)).isoformat())
        self.assertIsNone(c.announced_at)
        self.assertFalse(Notification.objects.filter(user=self.resp).exists())
        daily(TODAY + dt.timedelta(days=2))
        self.assertEqual(Notification.objects.filter(user=self.resp).count(), 1)
        reminder_day = c.deadline - dt.timedelta(days=3)
        daily(reminder_day)
        daily(reminder_day)  # não repete
        self.assertEqual(Notification.objects.filter(user=self.resp, title__contains="prazo termina").count(), 1)
        Notification.objects.all().delete()
        with mock.patch("django.utils.timezone.localdate", return_value=TODAY + dt.timedelta(days=3)):
            self.answer(c)
        Campaign.objects.filter(pk=c.pk).update(reminded_on=None)
        daily(reminder_day)
        self.assertFalse(Notification.objects.filter(user=self.resp).exists())  # já respondeu

    def test_chosen_classes_limit_scope_and_target_year_must_be_next(self):
        self.login("sec")
        resp = self.client.post(reverse("reenroll:create"), {
            "title": "X", "target_year": self.year.pk, "opens_on": TODAY.isoformat(),
            "deadline": (TODAY + dt.timedelta(days=5)).isoformat()})
        self.assertContains(resp, "não o ano letivo atual")
        c = self.open_campaign(class_groups=[self.turma_b.pk])  # só a turma da Beatriz
        self.assertFalse(Notification.objects.filter(user=self.resp).exists())
        self.login("resp")
        self.assertEqual(self.client.get(reverse("reenroll:answer", args=[c.pk]) + f"?estudante={self.ana.pk}")
                         .status_code, 404)

    def test_rollover_unchecks_who_is_leaving(self):
        c = self.open_campaign()
        self.answer(c, decision="sai", reason="mudanca")
        ClassGroup.objects.create(school=self.school, school_year=self.next, name="2º Ano A")
        self.year.end_date = TODAY - dt.timedelta(days=1)
        self.year.save()
        self.login("sec")
        html = self.client.get(reverse("enrollment_rollover") + f"?origem={self.turma.pk}").content.decode()
        e = Enrollment.objects.get(student=self.ana)
        box = re.search(rf'<input[^>]*name="ids" value="{e.pk}"[^>]*>', html).group(0)
        self.assertNotIn("checked", box)
        self.assertIn("Não vai continuar", html)
