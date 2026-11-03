"""Responsável com vínculo ainda pendente: os itens do menu abrem vazios, com o motivo, nunca em 403.

Achado no ensaio de atualização do banco real (03/11/2026): /autorizacoes/ e /consultas/ davam 403.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.models import Role
from apps.registry.models import GuardianLink

from .test_communication import CommunicationBase


class PendingFamilyListsTests(CommunicationBase):
    def test_lists_open_empty_with_the_reason(self):
        waiting = get_user_model().objects.create_user("resp_pendente", password="senha-forte-1",
                                                       role=Role.RESPONSAVEL, school=self.school)
        GuardianLink.objects.create(school=self.school, guardian=waiting, student=self.ana, status="pendente")
        self.client.force_login(waiting)
        for name in ("communication:authorization_list", "communication:poll_list"):
            page = self.client.get(reverse(name))
            self.assertContains(page, "Quando a escola aprovar o vínculo com seu filho", msg_prefix=name)
        self.client.force_login(self.sec)  # a regra da equipe não mudou
        self.assertEqual(self.client.get(reverse("communication:poll_list")).status_code, 200)
