"""Atendimentos de saúde: registro pelo professor ou pela equipe, aviso imediato à família, ciente e acesso."""

import datetime as dt

from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification, NotificationMute
from apps.communication.tests.test_communication import CommunicationBase
from apps.core.models import Role, User

from ..models import HealthIncident, HealthRecord


class IncidentTests(CommunicationBase):
    def register(self, student=None, user="prof", **extra):
        self.login(user)
        data = {"happened_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "kind": "machucado",
                "place": "Pátio", "description": "Caiu correndo no recreio e ralou o joelho.",
                "care_given": "Lavamos e fizemos curativo. Ficou 10 minutos em repouso.", "outcome": "voltou", **extra}
        return self.client.post(reverse("care:incident_create", args=[(student or self.ana).pk]), data)

    def test_teacher_registers_and_family_is_told_at_once_and_acknowledges(self):
        HealthRecord.objects.create(school=self.school, student=self.ana, allergies="Dipirona")
        self.login("prof")
        self.assertContains(self.client.get(reverse("care:incident_create", args=[self.ana.pk])), "Dipirona")
        self.register(head_hit="on")
        inc = HealthIncident.objects.get()
        self.assertEqual((inc.registered_by, inc.student), (self.prof, self.ana))
        note = Notification.objects.get(user=self.resp, kind="saude")
        self.assertEqual(note.priority, "importante")
        self.assertIn("Bateu a cabeça", note.body)
        self.login("resp")
        self.assertContains(self.client.get(reverse("pending_center")), "Atendimentos de saúde na escola sem o seu ciente")
        page = self.client.get(reverse("care:incident", args=[inc.pk]))
        self.assertContains(page, "ralou o joelho")
        self.assertContains(page, "Estou ciente")
        self.client.post(reverse("care:incident_ack", args=[inc.pk]), {"recado": "Obrigada, vou observar."})
        inc.refresh_from_db()
        self.assertEqual(inc.acknowledged_by, self.resp)
        self.assertTrue(Notification.objects.filter(user=self.prof, body="Obrigada, vou observar.").exists())
        self.assertNotContains(self.client.get(reverse("pending_center")), "sem o seu ciente")

    def test_urgent_outcome_and_family_cannot_mute_health(self):
        NotificationMute.objects.create(user=self.resp, kind="saude")
        self.register(kind="febre", outcome="buscar", description="Febre de 38,5 depois do lanche.",
                      care_given="Mediu a temperatura e ligou para a mãe.")
        note = Notification.objects.get(user=self.resp)
        self.assertTrue(note.title.startswith("Urgente: Ana"))

    def test_access_rules(self):
        self.assertEqual(self.register(student=self.bea).status_code, 403)  # não é aluna do professor
        self.register()
        inc = HealthIncident.objects.get()
        other = User.objects.create_user(username="prof2", password="senha-forte-1", role=Role.PROFESSOR,
                                         school=self.school)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("care:incident", args=[inc.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("care:incidents")), "Ana")
        self.login("sec")
        self.assertEqual(self.client.get(reverse("care:incident", args=[inc.pk])).status_code, 200)
        self.login("prof_b")
        self.assertIn(self.client.get(reverse("care:incident", args=[inc.pk])).status_code, (403, 404))
        self.login("resp_b")
        self.assertIn(self.client.get(reverse("care:incident", args=[inc.pk])).status_code, (403, 404))
        self.login("sec")  # só a família marca ciente
        self.assertEqual(self.client.post(reverse("care:incident_ack", args=[inc.pk])).status_code, 403)

    def test_time_must_be_recent_and_not_future(self):
        future = (timezone.localtime() + dt.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
        self.register(happened_at=future)
        old = (timezone.localtime() - dt.timedelta(days=9)).strftime("%Y-%m-%dT%H:%M")
        self.register(happened_at=old)
        self.assertFalse(HealthIncident.objects.exists())

    def test_teacher_finds_only_own_students(self):
        self.login("prof")
        page = self.client.get(reverse("care:incident_pick") + "?q=a")
        names = [f["s"].first_name for f in page.context["found"]]
        self.assertEqual(names, ["Ana"])
