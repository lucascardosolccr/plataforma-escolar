"""Terceira rodada de busca de melhorias (30/10/2026).

Cada teste aqui reprovou no código anterior à correção que ele cobre.
"""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.academics.models import SchoolYear
from apps.core.models import Role
from apps.core.tests.test_redesign_round2 import Round2Base
from apps.pedagogy.models import Occurrence
from apps.registry.models import Student


class SchoolYearFormSideEffectTests(Round2Base):
    """Marcar "ano letivo atual" num formulário recusado não pode desmarcar o
    ano atual de verdade: a escola ficaria sem ano corrente."""

    def test_invalid_form_keeps_current_year(self):
        atual = SchoolYear.objects.get(school=self.school)
        atual.is_current = True
        atual.save()
        self.login(self.users[Role.ADMIN])
        resp = self.client.post(reverse("school_year_create"), {
            "name": "2027", "start_date": "2027-12-01", "end_date": "2027-02-01", "is_current": "on",
        })
        self.assertEqual(resp.status_code, 200)  # recusado: fim antes do início
        atual.refresh_from_db()
        self.assertTrue(atual.is_current)

    def test_valid_form_moves_current_year(self):
        atual = SchoolYear.objects.get(school=self.school)
        atual.is_current = True
        atual.save()
        self.login(self.users[Role.ADMIN])
        self.client.post(reverse("school_year_create"), {
            "name": "2027", "start_date": "2027-02-01", "end_date": "2027-12-01", "is_current": "on",
        })
        atual.refresh_from_db()
        self.assertFalse(atual.is_current)
        self.assertTrue(SchoolYear.objects.get(name="2027").is_current)


class StudentChoicesTests(Round2Base):
    """O professor escolhe só entre os estudantes das próprias turmas."""

    def setUp(self):
        super().setUp()
        self.carla = Student.objects.create(school=self.school, first_name="Carla", last_name="Fora")

    def test_teacher_lists_only_own_students(self):
        self.login(self.prof)
        for name in ("pedagogy:occurrence_create", "pedagogy:observation_create"):
            page = self.client.get(reverse(name))
            choices = list(page.context["form"].fields["student"].queryset)
            self.assertIn(self.ana, choices, name)
            self.assertNotIn(self.carla, choices, name)

    def test_coordination_still_sees_the_school(self):
        self.login(self.users[Role.COORDENACAO])
        page = self.client.get(reverse("pedagogy:occurrence_create"))
        self.assertIn(self.carla, list(page.context["form"].fields["student"].queryset))


class FutureDatesTests(Round2Base):
    def test_occurrence_cannot_be_in_the_future(self):
        self.login(self.prof)
        amanha = (timezone.localdate() + timedelta(days=1)).isoformat()
        resp = self.client.post(reverse("pedagogy:occurrence_create"), {
            "student": self.ana.pk, "date": amanha, "description": "Teste", "status": "aberta",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "não pode ter data futura")
        self.assertFalse(Occurrence.objects.exists())

    def test_birth_date_cannot_be_in_the_future(self):
        self.login(self.users[Role.SECRETARIA])
        amanha = (timezone.localdate() + timedelta(days=1)).isoformat()
        resp = self.client.post(reverse("student_edit", args=[self.ana.pk]), {
            "first_name": "Ana", "last_name": "Souza", "birth_date": amanha, "status": self.ana.status,
        })
        self.assertContains(resp, "não pode ser futura")
        self.ana.refresh_from_db()
        self.assertIsNone(self.ana.birth_date)
