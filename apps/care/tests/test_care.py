"""Ficha de saúde (quem vê o quê, consentimento, auditoria) e retirada (lista, aviso, registro e avisos)."""

import datetime as dt

from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification, NotificationMute
from apps.communication.tests.test_communication import CommunicationBase
from apps.core.models import AuditLog
from apps.gate.models import GateEvent

from ..models import AuthorizedPickup, DepartureNotice, EmergencyContact, HealthRecord, PickupRecord

HEALTH = {"allergies": "Amendoim: fecha a garganta", "diet": "sem_lactose", "diet_notes": "", "conditions": "Asma",
          "medications": "Bombinha de salbutamol, se tiver crise", "crisis_plan": "Sentar, bombinha, ligar para a mãe",
          "insurance": "Plano X", "emergency_transport": "on", "consent": "on",
          "c0-name": "Maria Souza", "c0-relationship": "mãe", "c0-phone": "(11) 99999-0000",
          "c1-name": "João Souza", "c1-relationship": "avô", "c1-phone": "(11) 98888-0000"}


class CareBase(CommunicationBase):
    def fill(self, user="resp", **extra):
        self.login(user)
        return self.client.post(reverse("care:health_edit", args=[self.ana.pk]), {**HEALTH, **extra})

    def record(self):
        return HealthRecord.objects.create(school=self.school, student=self.ana, allergies="Amendoim",
                                           medications="Remédio secreto", insurance="Plano X")


class HealthTests(CareBase):
    def test_family_fills_with_consent_and_contacts(self):
        resp = self.fill()
        self.assertRedirects(resp, reverse("care:health", args=[self.ana.pk]))
        rec = HealthRecord.objects.get(student=self.ana)
        self.assertEqual((rec.consent_by, rec.diet), (self.resp, "sem_lactose"))
        self.assertTrue(rec.emergency_transport)
        self.assertEqual(list(EmergencyContact.objects.filter(student=self.ana).values_list("name", "order")),
                         [("Maria Souza", 1), ("João Souza", 2)])
        # Atualizar substitui os contatos, sem duplicar.
        self.fill(**{"c1-name": "", "c1-relationship": "", "c1-phone": ""})
        self.assertEqual(EmergencyContact.objects.filter(student=self.ana).count(), 1)

    def test_without_consent_or_with_half_contact_nothing_is_saved(self):
        data = dict(HEALTH)
        data.pop("consent")
        self.login("resp")
        self.client.post(reverse("care:health_edit", args=[self.ana.pk]), data)
        self.fill(**{"c2-name": "Só o nome"})
        self.assertFalse(HealthRecord.objects.exists())

    def test_teacher_sees_only_classroom_alerts_and_is_audited(self):
        self.record()
        EmergencyContact.objects.create(student=self.ana, name="Maria Souza", relationship="mãe", phone="1")
        self.login("prof")
        page = self.client.get(reverse("care:health", args=[self.ana.pk]))
        self.assertContains(page, "Amendoim")
        self.assertNotContains(page, "Remédio secreto")
        self.assertNotContains(page, "Maria Souza")
        self.assertNotContains(page, "Plano X")
        self.assertTrue(AuditLog.objects.filter(user=self.prof, action="view", detail__contains="alertas").exists())
        self.assertEqual(self.client.get(reverse("care:health_edit", args=[self.ana.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("care:health", args=[self.bea.pk])).status_code, 403)

    def test_office_sees_everything_family_view_is_not_audited(self):
        self.record()
        self.login("sec")
        self.assertContains(self.client.get(reverse("care:health", args=[self.ana.pk])), "Remédio secreto")
        self.assertTrue(AuditLog.objects.filter(user=self.sec, action="view").exists())
        self.login("resp")
        self.assertContains(self.client.get(reverse("care:health", args=[self.ana.pk])), "Remédio secreto")
        self.assertFalse(AuditLog.objects.filter(user=self.resp, action="view").exists())

    def test_other_family_and_other_school_are_refused(self):
        self.record()
        self.login("resp")
        self.assertEqual(self.client.get(reverse("care:health", args=[self.bea.pk])).status_code, 403)
        self.login("resp_b")
        self.assertEqual(self.client.get(reverse("care:health", args=[self.ana.pk])).status_code, 404)

    def test_class_alerts_and_food_list(self):
        self.record()
        HealthRecord.objects.create(school=self.school, student=self.bea)  # sem alerta: não aparece
        self.login("prof")
        page = self.client.get(reverse("care:class_alerts", args=[self.turma.pk]))
        self.assertContains(page, "Amendoim")
        self.assertEqual(self.client.get(reverse("care:class_alerts", args=[self.turma_b.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("care:food")).status_code, 403)
        self.login("sec")
        self.assertContains(self.client.get(reverse("care:food")), "Ana")
        self.assertContains(self.client.get(reverse("rotina:menu")), "Restrições alimentares (1)")


class PickupTests(CareBase):
    def add(self, user="resp", **extra):
        self.login(user)
        data = {"name": "Rosa Lima", "relationship": "avó", "document_hint": "RG final 4821", "phone": "", **extra}
        return self.client.post(reverse("care:pickups", args=[self.ana.pk]), data)

    def test_family_manages_the_list(self):
        self.add()
        p = AuthorizedPickup.objects.get(student=self.ana)
        self.assertEqual(p.created_by, self.resp)
        self.assertEqual(self.add(valid_until="2000-01-01").status_code, 200)  # data passada: recusada
        self.client.post(reverse("care:pickup_revoke", args=[p.pk]))
        p.refresh_from_db()
        self.assertIsNotNone(p.revoked_at)

    def test_only_family_and_office_manage(self):
        self.assertEqual(self.add("prof").status_code, 403)
        self.login("resp")
        self.assertEqual(self.client.post(reverse("care:pickups", args=[self.bea.pk]), {}).status_code, 403)
        self.add("sec")
        self.assertTrue(AuthorizedPickup.objects.filter(created_by=self.sec).exists())

    def test_notice_shows_at_the_gate_and_registering_closes_it(self):
        self.add()
        p = AuthorizedPickup.objects.get()
        today = timezone.localdate()
        self.client.post(reverse("care:notice_create", args=[self.ana.pk]),
                         {"day": today.isoformat(), "time": "10:30", "pickup": p.pk, "reason": "dentista"})
        notice = DepartureNotice.objects.get()
        self.login("sec")
        self.assertContains(self.client.get(reverse("care:home")), "dentista")
        self.assertContains(self.client.get(reverse("gate:today")), "Saídas antecipadas avisadas")
        self.assertContains(self.client.get(reverse("care:register", args=[self.ana.pk])), f'value="a:{p.pk}" checked')
        self.client.post(reverse("care:register", args=[self.ana.pk]), {"quem": f"a:{p.pk}"})
        rec = PickupRecord.objects.get()
        self.assertEqual((rec.kind, rec.person_name, rec.recorded_by), ("autorizada", "Rosa Lima", self.sec))
        notice.refresh_from_db()
        self.assertEqual(notice.status, "realizada")
        self.assertTrue(GateEvent.objects.filter(student=self.ana, kind="saida").exists())
        self.assertTrue(Notification.objects.filter(user=self.resp, title__contains="com Rosa Lima").exists())

    def test_notice_rules(self):
        self.login("resp")
        url = reverse("care:notice_create", args=[self.ana.pk])
        yesterday = timezone.localdate() - dt.timedelta(days=1)
        self.client.post(url, {"day": yesterday.isoformat(), "time": "10:00", "guardian_pickup": "on"})
        self.client.post(url, {"day": timezone.localdate().isoformat(), "time": "10:00"})  # sem quem busca
        self.assertFalse(DepartureNotice.objects.exists())
        self.client.post(url, {"day": timezone.localdate().isoformat(), "time": "10:00", "guardian_pickup": "on"})
        n = DepartureNotice.objects.get()
        self.client.post(reverse("care:notice_cancel", args=[n.pk]))
        n.refresh_from_db()
        self.assertEqual(n.status, "cancelada")

    def test_person_outside_the_list_needs_confirmation_and_alerts_the_family(self):
        NotificationMute.objects.create(user=self.resp, kind=Notification.Kind.GATE)  # silenciou a portaria
        self.login("sec")
        url = reverse("care:register", args=[self.ana.pk])
        page = self.client.post(url, {"quem": "o:", "nome": "Carlos"})
        self.assertContains(page, "confirme com um responsável")
        self.assertFalse(PickupRecord.objects.exists())
        self.client.post(url, {"quem": "o:", "nome": "Carlos", "confirmacao": "Liguei para a mãe às 10h05"})
        self.assertEqual(PickupRecord.objects.get().kind, "outra")
        alert = Notification.objects.get(user=self.resp, title__startswith="Atenção")
        self.assertEqual(alert.priority, "importante")
        self.assertIn("Liguei para a mãe", alert.body)

    def test_guardian_pickup_and_refusals(self):
        self.login("prof")
        self.assertEqual(self.client.get(reverse("care:register", args=[self.ana.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("care:pickups", args=[self.ana.pk])).status_code, 403)
        self.login("sec")
        self.client.post(reverse("care:register", args=[self.ana.pk]), {"quem": f"g:{self.prof.pk}"})  # não é responsável
        self.assertFalse(PickupRecord.objects.exists())
        self.client.post(reverse("care:register", args=[self.ana.pk]), {"quem": f"g:{self.resp.pk}"})
        self.assertEqual(PickupRecord.objects.get().guardian, self.resp)

    def test_family_home_lists_children(self):
        self.login("resp")
        page = self.client.get(reverse("care:home"))
        self.assertContains(page, "Ficha de saúde ainda não preenchida")
        self.assertNotContains(page, "Beatriz")
