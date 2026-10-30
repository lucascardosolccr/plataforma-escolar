"""Indicadores de cadastro, rotina e impressão no BI (Prompt 14, rodada 11)."""

from django.test import TestCase
from django.urls import reverse

from apps.academics.models import SchoolYear
from apps.analytics import bi
from apps.core.models import Role, School, User
from apps.registry.models import PhotoException, Student

PW = "Senha-forte-123"


class OperationalIndicatorTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        SchoolYear.objects.create(school=self.school, name="2026", is_current=True)
        self.dir = User.objects.create_user("dir", password=PW, role=Role.DIRECAO, school=self.school)
        Student.objects.create(school=self.school, first_name="Ana", photo="photos/a.jpg")
        bia = Student.objects.create(school=self.school, first_name="Bia")
        Student.objects.create(school=self.school, first_name="Caio")
        PhotoException.objects.create(school=self.school, student=bia, reason="Decisão judicial")

    def test_numbers_and_missing_data_rule(self):
        period = bi.resolve_period({}, self.school)
        ops = bi.operational_indicators(self.school, period)
        self.assertEqual((ops["students_active"], ops["photo_missing"], ops["photo_exempt"]), (3, 1, 1))
        self.assertAlmostEqual(ops["photo_pct"], 33.3, places=1)
        self.assertIsNone(ops["prints_on_time_pct"])  # sem entregas: "—", nunca 0
        self.assertIsNone(ops["school_days_left"])  # sem calendário publicado
        self.assertIn("datas", ops["calendar_reason"])

    def test_dashboard_and_quality_render_section(self):
        self.client.login(username="dir", password=PW)
        page = self.client.get(reverse("analytics:institutional_dashboard"))
        self.assertContains(page, "Cadastro, rotina e impressão")
        self.assertNotContains(page, "None%")
        self.assertContains(self.client.get(reverse("analytics:data_quality")), "Cadastro e rotina")
