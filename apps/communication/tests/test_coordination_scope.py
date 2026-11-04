"""Coordenação com designação restrita: mensagens e comunicados só para as turmas da designação.

O resto da plataforma já seguia ``coordination.scope.class_scope``; a lista de famílias para mensagem e os
comunicados não seguiam (achado da revisão de 04/11/2026)."""

from django.urls import reverse
from django.utils import timezone

from apps.communication import access as acc
from apps.communication.models import Announcement
from apps.coordination.models import CoordinatorAssignment

from .test_communication import CommunicationBase


class RestrictedCoordinationTests(CommunicationBase):
    coordenacao_restrita = True

    def setUp(self):
        super().setUp()
        CoordinatorAssignment.objects.create(school=self.school, coordinator=self.coord,
                                             starts_on=timezone.localdate()).class_groups.add(self.turma)

    def test_message_recipients_are_only_families_of_the_designation(self):
        from django.contrib.auth import get_user_model
        from apps.core.models import Role
        from apps.registry.models import GuardianLink

        resp_bea = get_user_model().objects.create_user("resp_bea", password="senha-forte-1",
                                                        role=Role.RESPONSAVEL, school=self.school)
        GuardianLink.objects.create(school=self.school, guardian=resp_bea, student=self.bea, status="aprovado")
        people = set(acc.guardian_recipients(self.coord))
        self.assertIn(self.resp, people)  # Ana, 1º Ano A (na designação)
        self.assertNotIn(resp_bea, people)  # Beatriz, 1º Ano B (fora)
        self.assertIn(resp_bea, set(acc.guardian_recipients(self.direc)))

    def test_announcements_follow_the_designation(self):
        S = Announcement.Scope
        self.assertTrue(acc.can_create_announcement(self.coord, S.TURMA, self.turma))
        self.assertFalse(acc.can_create_announcement(self.coord, S.TURMA, self.turma_b))
        self.assertTrue(acc.can_create_announcement(self.coord, S.INDIVIDUAL, student=self.ana))
        self.assertFalse(acc.can_create_announcement(self.coord, S.INDIVIDUAL, student=self.bea))
        self.assertFalse(acc.can_create_announcement(self.coord, S.INSTITUCIONAL))
        self.assertTrue(acc.can_create_announcement(self.direc, S.INSTITUCIONAL))
        self.client.force_login(self.coord)
        self.client.post(reverse("communication:announcement_create"),
                         {"scope": "turma", "audience": "familia", "class_group": self.turma_b.pk,
                          "title": "Fora", "body": "x"})
        self.assertFalse(Announcement.objects.filter(title="Fora").exists())
        self.client.post(reverse("communication:announcement_create"),
                         {"scope": "turma", "audience": "familia", "class_group": self.turma.pk,
                          "title": "Dentro", "body": "x"})
        self.assertTrue(Announcement.objects.filter(title="Dentro").exists())
