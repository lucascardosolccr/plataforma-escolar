"""Remédio na escola: pedido da família, conferência da receita, registro de cada dose e aviso à família."""

import datetime as dt
from unittest import mock

from django import forms
from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification
from apps.communication.tests.test_communication import CommunicationBase

from ..models import HealthRecord, MedicationDose, MedicationRequest
from ..views_meds import parse_times, schedule


class MedicationTests(CommunicationBase):
    def ask(self, **extra):
        self.login("resp")
        today = timezone.localdate()
        data = {"medicine": "Amoxicilina 250 mg/5 ml", "dose": "5 ml", "times": "10h e 14:30",
                "start_date": today.isoformat(), "end_date": (today + dt.timedelta(days=6)).isoformat(),
                "prescriber": "Dra. Paula, CRM 1234", "prescription_date": today.isoformat(), "authorize": "on",
                **extra}
        return self.client.post(reverse("care:medication_create", args=[self.ana.pk]), data)

    def approved(self):
        self.ask()
        req = MedicationRequest.objects.get()
        req.status, req.reviewed_by = MedicationRequest.Status.APPROVED, self.sec
        req.save()
        return req

    def test_times_are_read_the_way_families_write_them(self):
        self.assertEqual(parse_times("14:30, 10h e 9"), ["09:00", "10:00", "14:30"])
        self.assertEqual(parse_times("10h30; 13 h"), ["10:30", "13:00"])
        for bad in ("22:00", "depois do almoço", "", "25h"):
            with self.assertRaises(forms.ValidationError):
                parse_times(bad)

    def test_family_asks_and_office_is_told_to_check_the_prescription(self):
        self.ask()
        req = MedicationRequest.objects.get()
        self.assertEqual((req.times, req.status, req.requested_by), ("10:00, 14:30", "pendente", self.resp))
        self.assertTrue(Notification.objects.filter(user=self.sec, kind="saude", url__contains=f"/{req.pk}/").exists())
        self.assertFalse(Notification.objects.filter(user=self.prof).exists())
        # Sem autorização, horário fora da escola ou início no passado: não grava.
        self.ask(authorize="")
        self.ask(times="21:00")
        self.ask(start_date=(timezone.localdate() - dt.timedelta(days=1)).isoformat())
        self.assertEqual(MedicationRequest.objects.count(), 1)

    def test_who_can_ask_and_see(self):
        self.login("prof")
        self.assertEqual(self.client.get(reverse("care:medication_create", args=[self.ana.pk])).status_code, 403)
        self.login("resp")
        self.assertEqual(self.client.get(reverse("care:medication_create", args=[self.bea.pk])).status_code, 403)
        self.ask()
        req = MedicationRequest.objects.get()
        for user, code in (("prof", 403), ("resp_b", 404), ("sec", 200), ("coord", 200), ("resp", 200)):
            self.login(user)
            self.assertEqual(self.client.get(reverse("care:medication", args=[req.pk])).status_code, code, user)
        self.login("prof")
        self.assertEqual(self.client.get(reverse("care:medication_today")).status_code, 403)

    def test_review_needs_the_prescription_checked_and_a_reason_to_refuse(self):
        self.ask()
        req = MedicationRequest.objects.get()
        url = reverse("care:medication_review", args=[req.pk])
        self.login("coord")  # coordenação registra doses, mas não autoriza
        self.assertEqual(self.client.post(url, {"decision": "aprovar", "checked": "on"}).status_code, 403)
        self.login("sec")
        self.client.post(url, {"decision": "aprovar"})
        self.client.post(url, {"decision": "recusar"})
        req.refresh_from_db()
        self.assertEqual(req.status, "pendente")
        self.client.post(url, {"decision": "aprovar", "checked": "on"})
        req.refresh_from_db()
        self.assertEqual((req.status, req.reviewed_by), ("aprovado", self.sec))
        note = Notification.objects.get(user=self.resp, title__startswith="Remédio autorizado")
        self.assertIn("10:00, 14:30", note.body)

    def test_each_dose_is_recorded_once_and_the_family_is_told(self):
        req = self.approved()
        HealthRecord.objects.create(school=self.school, student=self.ana, allergies="Dipirona")
        self.login("sec")
        page = self.client.get(reverse("care:medication_today"))
        self.assertContains(page, "Dipirona")
        self.assertContains(page, "14:30")
        url = reverse("care:medication_dose", args=[req.pk])
        self.client.post(url, {"slot": "10:00", "result": "dado"})
        self.client.post(url, {"slot": "10:00", "result": "recusou"})  # repetido: fica o primeiro
        self.client.post(url, {"slot": "11:00", "result": "dado"})  # horário não autorizado
        self.client.post(url, {"slot": "14:30", "result": "nao_dado"})  # sem observação: recusado
        self.assertEqual(list(MedicationDose.objects.values_list("slot", "result")), [("10:00", "dado")])
        given = Notification.objects.get(user=self.resp, title="Ana tomou o remédio na escola")
        self.assertEqual(given.priority, "normal")
        self.client.post(url, {"slot": "14:30", "result": "recusou", "note": "Cuspiu o remédio."})
        missed = Notification.objects.get(user=self.resp, title="Ana não tomou o remédio das 14:30")
        self.assertEqual(missed.priority, "importante")
        self.assertIn("Cuspiu", missed.body)
        self.login("prof")
        self.assertEqual(self.client.post(url, {"slot": "10:00", "result": "dado"}).status_code, 403)

    def test_only_who_recorded_can_undo_and_only_right_away(self):
        req = self.approved()
        self.login("sec")
        self.client.post(reverse("care:medication_dose", args=[req.pk]), {"slot": "10:00", "result": "dado"})
        dose = MedicationDose.objects.get()
        self.login("dir")
        self.assertEqual(self.client.post(reverse("care:medication_dose_undo", args=[dose.pk])).status_code, 403)
        self.login("sec")
        MedicationDose.objects.filter(pk=dose.pk).update(given_at=timezone.now() - dt.timedelta(minutes=11))
        self.client.post(reverse("care:medication_dose_undo", args=[dose.pk]))
        self.assertTrue(MedicationDose.objects.exists())
        MedicationDose.objects.filter(pk=dose.pk).update(given_at=timezone.now())
        self.client.post(reverse("care:medication_dose_undo", args=[dose.pk]))
        self.assertFalse(MedicationDose.objects.exists())
        self.assertTrue(Notification.objects.filter(user=self.resp, title__startswith="Correção").exists())

    def test_late_doses_show_up_in_pending(self):
        req = self.approved()
        monday = dt.date(2026, 11, 9)
        MedicationRequest.objects.filter(pk=req.pk).update(start_date=monday - dt.timedelta(days=1),
                                                           end_date=monday + dt.timedelta(days=3))
        at = timezone.make_aware(dt.datetime(2026, 11, 9, 11, 0))
        with mock.patch("apps.care.views_meds.timezone.localtime", return_value=at):
            rows = schedule(self.sec, monday)
        self.assertEqual([(r["slot"], r["late"]) for r in rows], [("10:00", True), ("14:30", False)])
        saturday = dt.date(2026, 11, 14)
        MedicationRequest.objects.filter(pk=req.pk).update(end_date=saturday)
        at = timezone.make_aware(dt.datetime(2026, 11, 14, 16, 0))
        with mock.patch("apps.care.views_meds.timezone.localtime", return_value=at):
            self.assertFalse(any(r["late"] for r in schedule(self.sec, saturday)))  # fim de semana não atrasa

    def test_family_ends_and_school_stops(self):
        req = self.approved()
        self.login("resp")
        self.client.post(reverse("care:medication_end", args=[req.pk]))
        req.refresh_from_db()
        self.assertEqual(req.status, "encerrado")
        self.assertTrue(Notification.objects.filter(user=self.sec, title__contains="encerrou").exists())
        self.login("sec")
        self.client.post(reverse("care:medication_dose", args=[req.pk]), {"slot": "10:00", "result": "dado"})
        self.assertFalse(MedicationDose.objects.exists())
        self.assertNotContains(self.client.get(reverse("care:medication_today")), "Amoxicilina")
