"""Controlador e encarregado de dados (LGPD, art. 41): página pública, edição só pela gestão."""

from django.urls import reverse

from apps.communication.tests.test_communication import CommunicationBase
from apps.core.models import AuditLog, PrivacyContact


class PrivacyContactTests(CommunicationBase):
    def _publish(self):
        self.client.force_login(self.direc)
        return self.client.post(reverse("privacy_edit"), {
            "controller": "Secretaria de Estado de Educação", "officer_name": "Rosângela Pires",
            "officer_email": "encarregado@escola.example", "officer_phone": "(61) 3333-0000",
            "channel": "Pela plataforma, em Solicitações.", "responders": "Direção e secretaria"})

    def test_management_publishes_and_anyone_reads_without_login(self):
        self.assertEqual(self._publish().status_code, 302)
        self.assertTrue(AuditLog.objects.filter(detail__startswith="Atualizou o encarregado de dados").exists())
        self.client.logout()
        page = self.client.get(reverse("privacy"))
        self.assertContains(page, "Rosângela Pires")
        self.assertContains(page, "encarregado@escola.example")
        self.assertContains(self.client.get(reverse("login")), reverse("privacy"))

    def test_family_sees_the_officer_when_asking_and_only_management_edits(self):
        self._publish()
        self.client.force_login(self.resp)
        form = self.client.get(reverse("communication:request_create") + "?categoria=lgpd")
        self.assertContains(form, "Rosângela Pires")
        for user in (self.prof, self.coord, self.sec, self.resp):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("privacy_edit")).status_code, 403, user.username)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("privacy_edit")).status_code, 200)
        self.assertEqual(PrivacyContact.objects.count(), 1)

    def test_management_is_reminded_while_nothing_is_published(self):
        self.client.force_login(self.direc)
        self.assertContains(self.client.get(reverse("privacy")), "A escola ainda não informou o encarregado")
