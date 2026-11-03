"""Trajetória acadêmica, indicadores precoces e validação retrospectiva (trajectory.py, ews_validation.py)."""

import datetime as dt
from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse

from apps.cognitio import ews_validation, trajectory as t
from apps.cognitio.alerts import generate_for_class
from apps.cognitio.models import LearningAlert, ModelRun
from apps.cognitio.tests.test_evidence import Base
from apps.core.models import AuditLog
from apps.pedagogy.models import AttendanceRecord, Evaluation, Grade

D0 = dt.date(2026, 3, 2)


def series(values, step=10):
    return [(D0 + dt.timedelta(days=step * i), v) for i, v in enumerate(values)]


class StatisticsTests(SimpleTestCase):
    def test_theil_sen_ignores_an_outlier_that_would_bend_least_squares(self):
        xs = list(range(10))
        self.assertEqual(t.theil_sen(xs, [2 * x + 1 for x in xs]), (2.0, 1.0))
        self.assertEqual(t.theil_sen(xs, [2 * x + 1 if x != 5 else 100 for x in xs]), (2.0, 1.0))

    def test_mann_kendall_separates_trend_from_noise(self):
        self.assertLess(t.mann_kendall([1, 2, 3, 4, 5, 6, 7, 8])[2], 0.01)
        self.assertEqual(t.mann_kendall([5] * 8)[2], 1.0)  # só empates: nenhuma tendência
        self.assertGreater(t.mann_kendall([5, 7, 4, 6, 5, 7, 4, 6])[2], 0.5)

    def test_cusum_marks_only_a_drop_still_in_course(self):
        ongoing = [0.8, 0.82, 0.79, 0.81, 0.8, 0.78, 0.5, 0.45, 0.48, 0.44]
        self.assertEqual(t.cusum_drop(ongoing), 6)
        recovered = [0.72, 0.76, 0.78, 0.97, 0.36, 0.58, 0.81, 0.91]  # uma prova ruim e recuperação
        self.assertIsNone(t.cusum_drop(recovered))
        small = [0.8, 0.8, 0.8, 0.8, 0.75, 0.74, 0.75, 0.74]  # 0,5 ponto: abaixo do mínimo de mudança
        self.assertIsNone(t.cusum_drop(small))

    def test_analysis_needs_enough_points_and_never_projects_with_zero_width(self):
        self.assertEqual(t.analyse(series([0.9, 0.5, 0.3]))["trend"], "insuficiente")
        a = t.analyse(series([0.9 - 0.06 * i for i in range(8)]), horizon=D0 + dt.timedelta(days=90))
        self.assertEqual(a["trend"], "queda")
        self.assertTrue(a["preliminary"])  # menos de 14 pontos
        self.assertGreaterEqual(a["projection"]["high"] - a["projection"]["low"], 0.19)  # piso de ±2 × 0,05
        far = t.analyse(series([0.9 - 0.06 * i for i in range(8)]), horizon=D0 + dt.timedelta(days=400))
        self.assertEqual(far["projection"]["date"], D0 + dt.timedelta(days=70 + t.MAX_PROJECTION_DAYS))

    def test_auc_and_quantile(self):
        self.assertAlmostEqual(t.auc([3, 2, 2], [0, 1, 2]), 8 / 9)
        self.assertEqual(t.auc([1], [1]), 0.5)
        self.assertIsNone(t.auc([], [1]))
        self.assertEqual(t.quantile([1, 2, 3, 4], 0.25), 1.75)


class TrajectoryDataBase(Base):
    def grades(self, values_by_student, start=None, step=10):
        start = start or self.today - dt.timedelta(days=step * (len(next(iter(values_by_student.values()))) - 1))
        for i in range(len(next(iter(values_by_student.values())))):
            ev = Evaluation.objects.create(school=self.school, class_group=self.cg, subject=self.mat,
                                           title=f"Avaliação {i}", date=start + dt.timedelta(days=step * i),
                                           created_by=self.prof, status="publicada")
            for student, values in values_by_student.items():
                Grade.objects.create(school=self.school, evaluation=ev, student=student, value=values[i])


class ClassOverviewTests(TrajectoryDataBase):
    def test_declining_student_gets_trajectory_and_performance_indicators(self):
        self.grades({self.ana: [8, 7, 6, 5, 4.5, 4, 3, 2], self.bia: [8] * 8, self.caio: [7, 7.5, 7, 7.5, 7, 7.5, 7, 7.5]})
        for i in range(12):  # Bia falta 4 de 12 aulas: ausência crônica
            AttendanceRecord.objects.create(school=self.school, class_group=self.cg, student=self.bia,
                                            date=self.today - dt.timedelta(days=i), status="falta" if i < 4 else "presente")
        view = t.class_overview(self.cg, self.today - dt.timedelta(days=100), self.today)
        keys = {r["student"]: {i["key"] for i in r["indicators"]} for r in view["rows"]}
        self.assertEqual(keys[self.ana], {"trajetoria", "desempenho"})
        self.assertEqual(keys[self.bia], {"frequencia"})
        self.assertEqual(keys[self.caio], set())
        ana = next(r for r in view["rows"] if r["student"] == self.ana)
        self.assertEqual(ana["overall"]["trend"], "queda")
        detail = next(i["detail"] for i in ana["indicators"] if i["key"] == "trajetoria")
        self.assertIn("queda em Matemática", detail)  # nome da disciplina como cadastrado
        self.assertIsNone(ana["dual"])  # 3 estudantes: poucos colegas para comparar

    def test_teacher_sees_own_subjects_family_never_and_views_are_audited(self):
        self.grades({self.ana: [9, 8.5, 8, 7, 6, 5, 4, 3]})
        page_cls = reverse("cognitio:class_trajectories", args=[self.cg.pk])
        page_st = reverse("cognitio:student_trajectory", args=[self.ana.pk])
        self.login(self.prof)
        r = self.client.get(page_cls)
        self.assertContains(r, "Trajetória em queda")
        self.assertContains(r, "Notas só das suas disciplinas")
        r = self.client.get(page_st)
        self.assertContains(r, 'class="chart-trend"')
        self.assertContains(r, "Matemática")
        self.assertTrue(AuditLog.objects.filter(detail__startswith="Consultou a trajetória acadêmica").exists())
        for user in (self.fam, self.sec, self.prof_b):
            self.login(user)
            self.assertEqual(self.client.get(page_st).status_code, 403, user.username)
        self.login(self.prof_geo)  # leciona Geografia: não vê as notas de Matemática
        self.assertNotContains(self.client.get(page_st), "Avaliação 0")
        self.assertNotIn("Matemática", self.client.get(page_cls).content.decode().split("<tbody>")[0])

    def test_alert_center_receives_the_trajectory_rule(self):
        self.grades({self.ana: [9, 8.5, 8, 7, 6, 5, 4, 3], self.bia: [8] * 8})
        generate_for_class(self.cg, self.today)
        alert = LearningAlert.objects.get(rule="trajetoria")
        self.assertEqual(alert.student, self.ana)
        self.assertIn("Notas em queda", alert.explanation)


class RetrospectiveValidationTests(TrajectoryDataBase):
    def setUp(self):
        super().setUp()
        year = self.cg.school_year
        year.start_date, year.end_date = dt.date(2026, 2, 1), dt.date(2026, 12, 15)
        year.save()
        self.today = dt.date(2026, 11, 3)

    def test_indicators_use_only_data_before_the_cutoff(self):
        # Ana ia bem até 02/04 e despencou depois: na data de corte nenhum indicador pode "saber" disso.
        self.grades({self.ana: [9, 9, 9, 9, 2, 2, 2], self.bia: [8, 8, 8, 8, 8, 8, 8]},
                    start=dt.date(2026, 3, 3), step=8)
        rows = [r for r in ews_validation.collect(self.school, self.today) if r["cutoff"] == "2026-04-02"]
        ana = next(r for r in rows if r["y"])
        self.assertEqual(ana["count"], 0)  # sem vazamento do futuro
        self.assertEqual(sum(r["y"] for r in rows), 1)

    def test_small_school_stays_insufficient_and_cannot_be_approved(self):
        self.grades({self.ana: [9, 8, 7, 6, 5, 4, 3], self.bia: [8] * 7}, start=dt.date(2026, 3, 3), step=8)
        run = ews_validation.run(self.school, today=self.today)
        self.assertEqual(run.status, ModelRun.Status.INSUFFICIENT)
        self.assertIn("por_turno", run.metrics)
        self.login(self.dir)
        self.client.post(reverse("cognitio:models"), {"acao": "aprovar", "id": run.pk})
        run.refresh_from_db()
        self.assertEqual(run.status, ModelRun.Status.INSUFFICIENT)
        self.assertContains(self.client.get(reverse("cognitio:models")), "1 ou mais indicadores")

    def test_extreme_base_rate_is_flagged_as_not_approvable(self):
        m = {"n": 500, "positivos": 470, "taxa_base": 0.94}
        rows = [{"flags": [], "count": 0, "y": i < 470, "class": "A", "turn": "Manhã", "cutoff": "2026-04-02"}
                for i in range(500)]
        self.assertEqual(ews_validation.metrics(rows)["taxa_base"], m["taxa_base"])
        with mock.patch.object(ews_validation, "collect", return_value=rows):
            run = ews_validation.run(self.school, today=self.today)
        self.assertEqual(run.status, ModelRun.Status.INSUFFICIENT)
        self.assertIn("não pode ser aprovada", run.metrics["aviso"])
