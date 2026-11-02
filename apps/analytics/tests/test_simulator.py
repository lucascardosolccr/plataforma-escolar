"""Simulador de cenários (Prompt 6 §6.8, Prompt 9 §5.3): contas, acesso e
garantia de que nada é gravado."""

from datetime import date, timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.pedagogy.models import AcademicRule, AttendanceRecord, Evaluation, Grade
from apps.registry.models import GuardianLink

from .. import simulator
from .test_analytics import AnalyticsBase

D = Decimal
F = AcademicRule.Formula


class NeededGradeTests(AnalyticsBase):
    def test_arithmetic(self):
        # (5 + 6 + x) / 3 >= 6  ->  x >= 7
        self.assertEqual(simulator.needed_grade([(D(5), D(1)), (D(6), D(1))], F.ARITHMETIC, D(6)), D("7.00"))

    def test_arithmetic_rounds_up(self):
        # (5 + x) / 2 >= 5,995  ->  x >= 6,99  (nunca arredonda para baixo)
        self.assertEqual(simulator.needed_grade([(D(5), D(1))], F.ARITHMETIC, D("5.995")), D("6.99"))

    def test_weighted_uses_the_new_weight(self):
        # (4*1 + x*2) / 3 >= 6  ->  x >= 7
        self.assertEqual(simulator.needed_grade([(D(4), D(1))], F.WEIGHTED, D(6), D(2)), D("7.00"))

    def test_best_and_sum(self):
        self.assertEqual(simulator.needed_grade([(D(8), D(1))], F.BEST, D(6)), D(0))
        self.assertEqual(simulator.needed_grade([(D(4), D(1))], F.BEST, D(6)), D(6))
        self.assertEqual(simulator.needed_grade([(D(20), D(1)), (D(25), D(1))], F.SUM, D(60)), D("15.00"))

    def test_already_guaranteed_is_zero(self):
        self.assertEqual(simulator.needed_grade([(D(10), D(1)), (D(10), D(1))], F.ARITHMETIC, D(6)), D(0))

    def test_simulated_average_matches_formula(self):
        self.assertEqual(simulator.simulate_average([(D(4), D(1))], F.WEIGHTED, D(7), D(2)), D(6))


class AttendanceProjectionTests(AnalyticsBase):
    def test_projection_and_max_absences(self):
        # 80 presenças em 100 dias; faltam 100 dias; mínimo 75%.
        p = simulator.attendance_projection(80, 100, 100, 10, 25.0)
        self.assertEqual(p["projected"], 85.0)
        self.assertFalse(p["below"])
        # (80 + 100 - a) / 200 >= 0,75  ->  a <= 30. Exatamente 30, não 29.
        self.assertEqual(p["max_absences"], 30)

    def test_minimum_unreachable(self):
        p = simulator.attendance_projection(10, 100, 10, 0, 25.0)
        self.assertTrue(p["below"])
        self.assertEqual(p["max_absences"], -1)

    def test_inconsistent_input_gives_none(self):
        self.assertIsNone(simulator.attendance_projection(10, 20, 5, 6, 25.0))
        self.assertIsNone(simulator.attendance_projection(10, 20, None, 0, 25.0))


class SimulatorViewTests(AnalyticsBase):
    def setUp(self):
        super().setUp()
        today = timezone.localdate()
        for i, value in enumerate((D(5), D(6))):
            ev = Evaluation.objects.create(
                school=self.school, subject=self.mat, class_group=self.turma,
                title=f"Prova {i}", status=Evaluation.Status.PUBLISHED,
                date=today - timedelta(days=10 + i),
            )
            Grade.objects.create(school=self.school, evaluation=ev, student=self.ana, value=value)
        for i in range(8):
            AttendanceRecord.objects.create(
                school=self.school, class_group=self.turma, student=self.ana,
                date=today - timedelta(days=i + 1),
                status=AttendanceRecord.Status.ABSENT if i < 2 else AttendanceRecord.Status.PRESENT,
            )
        self.url = reverse("analytics:student_simulator", args=[self.ana.pk])

    def test_guardian_simulates_without_saving(self):
        self.client.login(username="resp", password="senha-forte-1")
        before = (Grade.objects.count(), AttendanceRecord.objects.count())
        resp = self.client.get(self.url, {f"nota_{self.mat.pk}": "7", "faltas": "1", "restantes": "12"})
        self.assertEqual(resp.status_code, 200)
        row = resp.context["rows"][0]
        self.assertEqual(row["current"], D("5.5"))
        self.assertEqual(row["needed"], D("7.00"))
        self.assertEqual(row["simulated"], D(6))
        # 6 presenças em 8 dias; 12 restantes com 1 falta: (6 + 11) / 20.
        self.assertEqual(resp.context["projection"]["projected"], 85.0)
        self.assertEqual(before, (Grade.objects.count(), AttendanceRecord.objects.count()))
        self.assertContains(resp, "Nada aqui é gravado")

    def test_invalid_input_is_reported_not_crashing(self):
        self.client.login(username="resp", password="senha-forte-1")
        resp = self.client.get(self.url, {f"nota_{self.mat.pk}": "abc", "faltas": "-3", "restantes": "x"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["rows"][0]["invalid"])
        self.assertTrue(resp.context["absences_invalid"])
        resp = self.client.get(self.url, {f"nota_{self.mat.pk}": "85"})  # fora da escala 0–10
        self.assertTrue(resp.context["rows"][0]["invalid"])

    def test_access_follows_the_dashboard(self):
        self.client.login(username="resp", password="senha-forte-1")
        other = reverse("analytics:student_simulator", args=[self.bea.pk])
        self.assertEqual(self.client.get(other).status_code, 403)
        GuardianLink.objects.filter(guardian=self.resp).update(status="pendente")
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.login(username="prof_b", password="senha-forte-1")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_teacher_sees_only_own_subjects(self):
        from apps.academics.models import Subject

        port = Subject.objects.create(school=self.school, name="Portugues")
        ev = Evaluation.objects.create(school=self.school, subject=port, class_group=self.turma,
                                       title="Redação", status=Evaluation.Status.PUBLISHED,
                                       date=timezone.localdate() - timedelta(days=3))
        Grade.objects.create(school=self.school, evaluation=ev, student=self.ana, value=D(9))
        self.client.login(username="prof", password="senha-forte-1")
        resp = self.client.get(self.url)
        self.assertEqual([r["subject"].name for r in resp.context["rows"]], ["Matematica"])
        self.client.login(username="coord", password="senha-forte-1")
        resp = self.client.get(self.url)
        self.assertEqual(len(resp.context["rows"]), 2)

    def test_draft_grades_are_not_used(self):
        ev = Evaluation.objects.create(school=self.school, subject=self.mat, class_group=self.turma,
                                       title="Rascunho", status=Evaluation.Status.DRAFT,
                                       date=timezone.localdate() - timedelta(days=2))
        Grade.objects.create(school=self.school, evaluation=ev, student=self.ana, value=D(0))
        self.client.login(username="resp", password="senha-forte-1")
        self.assertEqual(self.client.get(self.url).context["rows"][0]["current"], D("5.5"))

    def test_dashboard_links_to_simulator(self):
        self.client.login(username="resp", password="senha-forte-1")
        resp = self.client.get(reverse("analytics:student_dashboard", args=[self.ana.pk]))
        self.assertContains(resp, self.url)
