"""Boletins da turma para impressão (um por estudante, mesma regra do boletim individual)."""

from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.core.models import AuditLog
from apps.pedagogy.models import AttendanceRecord, Evaluation, Grade
from apps.registry.models import Enrollment, Student

from .test_bi_access import PW, Q, BIAccessBase


class ReportCardsTests(BIAccessBase):
    def setUp(self):
        super().setUp()
        self.caio = Student.objects.create(school=self.school, first_name="Caio")
        Enrollment.objects.create(school=self.school, student=self.caio, class_group=self.t1,
                                  school_year=self.t1.school_year)
        ev = Evaluation.objects.create(school=self.school, subject=self.mat, class_group=self.t1, title="P2",
                                       date=date(2026, 4, 10), status=Evaluation.Status.PUBLISHED, created_by=self.prof)
        Grade.objects.create(school=self.school, evaluation=ev, student=self.ana, value=Decimal("5"))
        Grade.objects.create(school=self.school, evaluation=ev, student=self.caio, value=Decimal("8"))
        AttendanceRecord.objects.create(school=self.school, class_group=self.t1, student=self.caio,
                                        date=date(2026, 4, 10), status="falta")
        self.url = reverse("analytics:class_report_cards", args=[self.t1.pk]) + Q

    def test_one_card_per_active_student_with_the_panel_rule(self):
        self.client.login(username="secretaria", password=PW)
        resp = self.client.get(self.url)
        cards = {c["student"].first_name: c for c in resp.context["cards"]}
        self.assertEqual(set(cards), {"=CMD", "Caio"})  # Bia é do 5º B
        self.assertEqual(float(cards["=CMD"]["subjects"][0]["average"]), 6.0)  # (7 + 5) / 2
        self.assertEqual(cards["Caio"]["attendance"]["absent"], 1)
        self.assertContains(resp, "Assinatura do(a) responsável", count=2)
        self.assertContains(resp, "6,00")
        self.assertTrue(AuditLog.objects.filter(detail__startswith="Abriu os boletins da turma 5º A").exists())

    def test_period_filters_the_grades(self):
        self.client.login(username="secretaria", password=PW)
        resp = self.client.get(reverse("analytics:class_report_cards", args=[self.t1.pk])
                               + "?periodo=personalizado&inicio=2026-04-01&fim=2026-04-30")
        ana = next(c for c in resp.context["cards"] if c["student"].pk == self.ana.pk)
        self.assertEqual(float(ana["subjects"][0]["average"]), 5.0)

    def test_access_and_button(self):
        self.matrix(self.url, {"admin", "direcao", "coordenacao", "secretaria"})
        self.client.login(username="direcao", password=PW)
        self.assertContains(self.client.get(reverse("analytics:class_dashboard", args=[self.t1.pk])),
                            reverse("analytics:class_report_cards", args=[self.t1.pk]))
        self.client.login(username="prof", password=PW)
        self.assertNotContains(self.client.get(reverse("analytics:class_dashboard", args=[self.t1.pk])),
                               "Boletins da turma para imprimir")
