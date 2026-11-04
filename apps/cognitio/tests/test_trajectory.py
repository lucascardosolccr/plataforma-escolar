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


class ThresholdTests(TrajectoryDataBase):
    def test_school_threshold_changes_who_is_flagged(self):
        from apps.cognitio.models import MasteryScale

        for i in range(12):  # Bia: 8 de 12 presenças = 67%
            AttendanceRecord.objects.create(school=self.school, class_group=self.cg, student=self.bia,
                                            date=self.today - dt.timedelta(days=i), status="falta" if i < 4 else "presente")
        start = self.today - dt.timedelta(days=30)
        flagged = lambda: any(i["key"] == "frequencia" for r in t.class_overview(self.cg, start, self.today)["rows"]
                              if r["student"] == self.bia for i in r["indicators"])
        self.assertTrue(flagged())  # padrão 90%
        scale = MasteryScale.for_school(self.school)
        scale.ews_attendance = 60
        scale.save()
        self.assertFalse(flagged())
        self.login(self.coord)
        r = self.client.post(reverse("cognitio:scale"), {"t1": "0.4", "t2": "0.6", "t3": "0.8", "min_evidence": 2,
                                                         "min_weight": "1.2", "half_life_days": 120, "stale_days": 60,
                                                         "ews_attendance": "40", "ews_delivery": "60",
                                                         "ews_occurrences": 2})
        self.assertContains(r, "Use um valor entre 50 e 100.")

    def test_threshold_table_marks_current_and_best_separation(self):
        rows = ([{"y": True, "att": 0.82, "att_n": 20, "occ": 0, "below": 1} for _ in range(10)]
                + [{"y": False, "att": 0.88, "att_n": 20, "occ": 0, "below": 0} for _ in range(30)]
                + [{"y": False, "att": 0.97, "att_n": 20, "occ": 0, "below": 0} for _ in range(60)])
        table = ews_validation.threshold_table(rows, {"attendance": 0.90, "delivery": 0.6, "occurrences": 2,
                                                      "below": 1})
        att = {ln["limiar"]: ln for ln in table["frequencia"]["linhas"]}
        self.assertTrue(att["presença abaixo de 90%"]["atual"])
        self.assertEqual(att["presença abaixo de 90%"]["precisao"], 0.25)  # 10 de 40 sinalizados
        self.assertTrue(att["presença abaixo de 85%"].get("maior_youden"))  # separa perfeitamente
        self.assertEqual((att["presença abaixo de 85%"]["sensibilidade"], att["presença abaixo de 85%"]["especificidade"]),
                         (1.0, 1.0))

    def test_assistant_answers_early_signals_and_trajectory_within_access(self):
        from apps.cognitio import assistant

        self.grades({self.ana: [8, 7, 6, 5, 4.5, 4, 3, 2], self.bia: [8] * 8})
        a = assistant.answer(self.prof, "Quem tem sinais precoces na turma?", class_group=self.cg)
        self.assertEqual(a.intent, "sinais_precoces")
        self.assertTrue(any(text.startswith("Ana:") for text, _ in a.items))
        a = assistant.answer(self.prof, "Como está a trajetória da Ana?")
        self.assertEqual(a.intent, "trajetoria")
        self.assertIn("queda", " ".join(a.paragraphs))
        a = assistant.answer(self.prof_b, "Como está a trajetória da Ana?")  # não leciona para a Ana
        self.assertTrue(a.missing)
        self.assertFalse(a.items)


class InterventionResponseTests(TrajectoryDataBase):
    def test_segment_change_reads_level_and_rhythm_on_each_side(self):
        cut = D0 + dt.timedelta(days=30)
        c = t.segment_change(series([0.4, 0.42, 0.38, 0.7, 0.72, 0.74]), cut)
        self.assertTrue(c["ok"])
        self.assertEqual(c["label"], "subiu")
        self.assertAlmostEqual(c["change"], 0.32, places=2)
        self.assertFalse(t.segment_change(series([0.4, 0.5, 0.7, 0.8]), cut)["ok"])  # 3 antes, 1 depois

    def test_intervention_page_compares_with_classmates(self):
        from apps.cognitio.models import LearningIntervention
        from apps.registry.models import Enrollment, Student

        for name in ("Davi", "Eva", "Fábio", "Gil"):  # colegas fora da intervenção (referência precisa de 5)
            st = Student.objects.create(school=self.school, first_name=name)
            Enrollment.objects.create(school=self.school, student=st, class_group=self.cg, school_year=self.cg.school_year)
        start = self.today - dt.timedelta(days=70)
        others = {s: [6, 6, 6, 6, 6.5, 6.5, 6.5, 6.5] for s in Student.objects.exclude(pk=self.ana.pk)}
        self.grades({self.ana: [3, 3, 3, 3, 6, 6.5, 7, 7], **others}, start=start)
        iv = LearningIntervention.objects.create(
            school=self.school, class_group=self.cg, subject=self.mat, item=self.h1, title="Retomada",
            objective="o", activity="a", starts_on=start + dt.timedelta(days=35), review_on=self.today,
            created_by=self.prof)
        iv.students.add(self.ana)
        r = t.intervention_response(iv)
        ana = r["rows"][0]
        self.assertEqual((ana["student"], ana["label"]), (self.ana, "subiu"))
        self.assertEqual(r["reference"], 0.05)  # colegas subiram meio ponto
        self.assertAlmostEqual(ana["vs_peers"], 0.3625 - 0.05, places=2)  # 3,625 − 0,5 pontos
        self.login(self.prof)
        page = self.client.get(reverse("cognitio:intervention_detail", args=[iv.pk]))
        self.assertContains(page, "regressão à média")
        self.assertContains(page, "+3,1")  # 3,625 pontos menos 0,5 dos colegas, na escala de 0 a 10

    def test_class_council_shows_early_signals(self):
        self.grades({self.ana: [8, 7, 6, 5, 4.5, 4, 3, 2], self.bia: [8] * 8})
        self.login(self.prof)
        page = self.client.get(reverse("cognitio:class_council", args=[self.cg.pk]))
        self.assertContains(page, "Trajetória em queda")
        self.assertContains(page, "com algum indicador precoce")


class WeeklyDigestTests(TrajectoryDataBase):
    def test_teachers_get_one_count_only_summary_per_week(self):
        from apps.cognitio.digest import weekly_digest
        from apps.communication.models import Notification, NotificationMute

        self.grades({self.ana: [8, 7, 6, 5, 4.5, 4, 3, 2], self.bia: [8] * 8})
        generate_for_class(self.cg, self.today)
        weekly_digest(self.today)
        note = Notification.objects.get(user=self.prof, kind="eia")
        self.assertIn("Trajetória em queda", note.body)
        self.assertNotIn("Ana", note.title + note.body)  # só contagens, nunca nomes
        self.assertFalse(Notification.objects.filter(user=self.prof_b, kind="eia").exists())  # outra turma
        weekly_digest(self.today)  # mesma semana: não repete
        self.assertEqual(Notification.objects.filter(user=self.prof, kind="eia").count(), 1)
        weekly_digest(self.today + dt.timedelta(days=7))  # semana seguinte sem sinal novo: nada
        self.assertEqual(Notification.objects.filter(user=self.prof, kind="eia").count(), 1)
        NotificationMute.objects.create(user=self.prof_geo, kind="eia")
        Notification.objects.filter(user=self.prof_geo).delete()
        weekly_digest(self.today + dt.timedelta(days=14))
        self.assertFalse(Notification.objects.filter(user=self.prof_geo, kind="eia").exists())

    def test_unchanged_alerts_are_not_rewritten_and_run_in_one_transaction(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.grades({self.ana: [8, 7, 6, 5, 4.5, 4, 3, 2], self.bia: [8] * 8})
        generate_for_class(self.cg, self.today)
        stamp = LearningAlert.objects.get(rule="trajetoria").updated_at
        with CaptureQueriesContext(connection) as ctx:
            generate_for_class(self.cg, self.today)
        self.assertFalse([q for q in ctx.captured_queries if q["sql"].startswith("UPDATE")])
        self.assertEqual(LearningAlert.objects.get(rule="trajetoria").updated_at, stamp)

