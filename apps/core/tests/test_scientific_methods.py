"""Métodos estatísticos da plataforma: valores conhecidos e o uso em cada tela (prova, turmas, médias, consultas,
frequência semanal)."""

import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import SchoolYear
from apps.analytics import spc
from apps.analytics.bi import compare_classes
from apps.analytics.services import _averages_from_grades
from apps.cognitio.models import QuestionResponse
from apps.cognitio.models import Question, QuestionSkill
from apps.cognitio.tests.test_evidence import Base as CognitioBase
from apps.communication.models import Poll, PollVote
from apps.communication.tests.test_communication import CommunicationBase
from apps.communication.views_polls import poll_margins
from apps.core import stats
from apps.pedagogy.models import AcademicRule, AttendanceRecord
from apps.registry.models import Enrollment, Student


class KnownValuesTests(TestCase):
    def test_t_welch_hedges_and_fdr(self):
        self.assertAlmostEqual(stats.t_two_sided_p(2.228, 10), 0.05, places=3)  # tabela t: 2,228 com 10 gl
        self.assertAlmostEqual(stats.t_two_sided_p(1.96, 10 ** 6), 0.05, places=3)
        w = stats.welch([1, 2, 3, 4, 5], [3, 4, 5, 6, 7, 8])
        self.assertAlmostEqual(w["t"], -2.4019, places=3)
        self.assertAlmostEqual(w["p"], 0.0398, places=3)
        g = stats.hedges_g([1, 2, 3, 4, 5], [3, 4, 5, 6, 7, 8])
        self.assertLess(g["g"], -1.0)
        self.assertLess(g["high"], 0)
        self.assertEqual(stats.effect_label(0.1), "desprezível")
        self.assertEqual(stats.effect_label(-0.9), "grande")
        q = stats.benjamini_hochberg([0.01, 0.04, 0.03, None, 0.2])
        self.assertEqual([round(v, 4) if v is not None else None for v in q], [0.04, 0.0533, 0.0533, None, 0.2])

    def test_inter_rater_agreement(self):
        cats = [1, 2, 3, 4, 5]
        # Concordância perfeita: tudo 1, qualquer coeficiente definido vale 1.
        perfeito = [(3, 3), (4, 4), (2, 2), (5, 5), (3, 3)]
        self.assertEqual(stats.percent_agreement(perfeito), {"exact": 1.0, "within1": 1.0, "pairs": 5})
        self.assertAlmostEqual(stats.weighted_kappa(perfeito, cats), 1.0, places=6)
        self.assertAlmostEqual(stats.gwet_ac2(perfeito, cats), 1.0, places=6)

        # Duas categorias, dados "ao acaso": kappa e AC2 = 0 (calculado à mão).
        acaso = [(0, 0), (1, 1), (0, 1), (1, 0)]
        self.assertAlmostEqual(stats.weighted_kappa(acaso, [0, 1]), 0.0, places=6)
        self.assertAlmostEqual(stats.gwet_ac2(acaso, [0, 1]), 0.0, places=6)

        # Paradoxo do kappa: 90% de concordância, mas quase tudo num nível só.
        paradoxo = [(1, 1)] * 18 + [(1, 2), (2, 1)]
        pa = stats.percent_agreement(paradoxo)
        self.assertAlmostEqual(pa["exact"], 0.9, places=6)
        self.assertAlmostEqual(stats.weighted_kappa(paradoxo, [1, 2]), -0.0526, places=3)  # despenca
        self.assertAlmostEqual(stats.gwet_ac2(paradoxo, [1, 2]), 0.8895, places=3)         # robusto

        # Peso quadrático: discordância de 1 nível conta como concordância parcial, não some.
        um_nivel = [(3, 4)] * 10
        self.assertEqual(stats.percent_agreement(um_nivel)["within1"], 1.0)
        self.assertGreater(stats.weighted_kappa([(3, 3)] * 9 + [(3, 4)], cats),
                           stats.weighted_kappa([(3, 3)] * 9 + [(3, 1)], cats))  # longe pune mais

        # Casos de guarda: sem pares, e uma única categoria (concordância esperada já é 1 → indefinido).
        self.assertIsNone(stats.weighted_kappa([], cats))
        self.assertIsNone(stats.weighted_kappa([(3, 3)] * 5, cats))
        self.assertEqual(stats.agreement_label(0.9), "quase perfeita")
        self.assertEqual(stats.agreement_label(-0.1), "pior que o acaso")

    def test_proportions(self):
        p, lo, hi = stats.wilson(37, 74, population=120)
        self.assertLess(hi - lo, stats.wilson(37, 74)[2] - stats.wilson(37, 74)[1])  # população finita estreita
        self.assertEqual(stats.wilson(120, 120, population=120), (1.0, 1.0, 1.0))
        d = stats.diff_of_shares(40, 35, 100)
        self.assertLess(d["low"], 0)  # 40% × 35% com 100 votos: empate técnico

    def test_categorical_association(self):
        table = [[3, 1], [1, 3]]  # "chá de senhora" de Fisher
        cs = stats.chi_square(table)
        self.assertEqual((round(cs["chi2"], 4), cs["dof"], cs["n"]), (2.0, 1, 8))
        self.assertAlmostEqual(cs["min_expected"], 2.0)
        self.assertAlmostEqual(stats.cramers_v(table), 0.5)  # V = √(2/8)
        self.assertAlmostEqual(stats.fisher_exact_2x2(3, 1, 1, 3), 34 / 70, places=4)  # p bicaudal ≈ 0,486
        # Independência perfeita: V = 0 e p = 1.
        self.assertAlmostEqual(stats.cramers_v([[2, 2], [2, 2]]), 0.0)
        self.assertAlmostEqual(stats.fisher_exact_2x2(2, 2, 2, 2), 1.0, places=6)

    def test_tukey_outliers(self):
        # [1,10,11,...,17]: Q1=11, Q3=15, IQR=4, cercas 5 e 21 → só o 1 é atípico (abaixo).
        out = stats.tukey_outliers([1, 10, 11, 12, 13, 14, 15, 16, 17])
        self.assertEqual((out["q1"], out["q3"], out["iqr"]), (11.0, 15.0, 4.0))
        self.assertEqual((out["low"], out["high"]), (5.0, 21.0))
        self.assertEqual((out["n_low"], out["n_high"], out["n_out"]), (1, 0, 1))
        self.assertIsNone(stats.tukey_outliers([5, 6, 7]))  # poucos dados → None

    def test_item_analysis_and_precision(self):
        res = stats.item_analysis([[1, 1, 0], [1, 0, 0], [1, 1, 1], [0, 0, 0], [1, 1, 1]])
        self.assertAlmostEqual(res["alpha"], 0.7941, places=3)  # KR-20 calculado à mão
        m, se = stats.weighted_mean_se([4, 6, 8])
        self.assertEqual(m, 6)
        self.assertAlmostEqual(se, 2 / 3 ** 0.5)  # s/√n

    def test_control_chart_rules(self):
        runs = stats.anhoej(list(range(20)))
        self.assertEqual((runs["run_limit"], runs["min_crossings"]), (7, 6))  # tabela de Anhøj & Olesen para n = 20
        self.assertTrue(runs["shift"])
        self.assertFalse(stats.anhoej([1, 2] * 10)["shift"])
        steady = [(i, 950 + (7 if i % 2 else -7), 1000) for i in range(12)]
        chart = stats.laney_p(steady + [(12, 700, 1000)])
        self.assertEqual(chart["points"][-1]["signal"], "abaixo")
        self.assertFalse(any(p["signal"] for p in chart["points"][:-1]))


class ItemQualityTests(CognitioBase):
    def setUp(self):
        super().setUp()
        self.url = reverse("cognitio:exam_analysis", args=[self.ev.pk])

    def question(self, n, main):
        q = Question.objects.create(evaluation=self.ev, number=n, label=f"Questão {n}", max_points=Decimal("2"))
        QuestionSkill.objects.create(question=q, item=main, role="principal")
        return q

    def answer(self, q, student, points):
        QuestionResponse.objects.create(question=q, student=student, points=Decimal(points))

    def test_question_that_separates_backwards_is_flagged(self):
        year = self.cg.school_year
        kids = list(self.students)
        for i in range(12 - len(kids)):
            s = Student.objects.create(school=self.school, first_name=f"K{i}")
            Enrollment.objects.create(school=self.school, student=s, class_group=self.cg, school_year=year)
            kids.append(s)
        qs = [self.question(n, self.h1) for n in (1, 2, 3, 4)]
        for rank, s in enumerate(kids):
            level = rank / (len(kids) - 1)
            for j, q in enumerate(qs[:3]):
                pts = 2 if level > 0.25 * (j + 1) - 0.05 else 0
                self.answer(q, s, str(pts))
            self.answer(qs[3], s, "0" if level > 0.5 else "2")  # quem vai bem erra: gabarito trocado?
        self.login(self.prof)
        r = self.client.get(self.url)
        quality = r.context["a"]["quality"]
        self.assertTrue(quality["enough"])
        flagged = {row["q"].number: row for row in quality["flagged"]}
        self.assertEqual(list(flagged), [4])
        self.assertEqual(flagged[4]["disc_flag"], "negativa")
        self.assertTrue(flagged[4]["better_without"])
        self.assertContains(r, "Qualidade da prova")
        self.assertContains(r, "Confira o gabarito")

    def test_contradictory_questions_give_negative_alpha_without_a_margin(self):
        year = self.cg.school_year
        kids = list(self.students)
        for i in range(12 - len(kids)):
            s = Student.objects.create(school=self.school, first_name=f"N{i}")
            Enrollment.objects.create(school=self.school, student=s, class_group=self.cg, school_year=year)
            kids.append(s)
        qs = [self.question(n, self.h1) for n in (1, 2, 3)]
        for rank, s in enumerate(kids):
            hi = rank % 2 == 0
            self.answer(qs[0], s, "2" if hi else "0")
            self.answer(qs[1], s, "0" if hi else "2")  # o oposto da primeira
            self.answer(qs[2], s, "2" if rank < 6 else "0")
        self.login(self.prof)
        r = self.client.get(self.url)
        quality = r.context["a"]["quality"]
        self.assertLess(quality["alpha"], 0)
        self.assertIsNone(quality["sem10"])
        self.assertContains(r, "Alfa negativo")

    def test_too_few_students_no_item_statistics(self):
        qs = [self.question(n, self.h1) for n in (1, 2, 3)]
        for q in qs:
            for s in self.students:
                self.answer(q, s, "1")
        self.login(self.prof)
        r = self.client.get(self.url)
        self.assertFalse(r.context["a"]["quality"]["enough"])
        self.assertContains(r, "A análise das questões precisa de")


class ClassComparisonTests(TestCase):
    def test_only_real_differences_after_correction(self):
        import random

        rnd = random.Random(5)
        classes = [{"small": False, "_vals": [rnd.gauss(7, 1) for _ in range(30)]} for _ in range(5)]
        classes.append({"small": False, "_vals": [rnd.gauss(4.5, 1) for _ in range(30)]})
        classes.append({"small": True, "_vals": [1.0, 1.0, 2.0]})
        compare_classes(classes)
        self.assertTrue(classes[5]["cmp"]["likely"])
        self.assertEqual(classes[5]["cmp"]["direction"], "abaixo")
        self.assertNotIn("cmp", classes[6])  # grupo pequeno fica de fora
        self.assertTrue(all("_vals" not in c for c in classes))
        same = [{"small": False, "_vals": [rnd.gauss(7, 1) for _ in range(25)]} for _ in range(8)]
        compare_classes(same)
        self.assertFalse(any(c["cmp"]["likely"] for c in same))  # 8 turmas iguais: nenhuma "diferença" por acaso


class AveragePrecisionTests(CommunicationBase):
    def _grades(self, values, weights=None):
        from apps.analytics.bi import _Ev, _LightGrade

        weights = weights or [1] * len(values)
        return [_LightGrade(Decimal(str(v)), _Ev(self.mat, Decimal(str(w)), timezone.localdate()), i)
                for i, (v, w) in enumerate(zip(values, weights))]

    def test_near_the_cut_only_when_the_difference_fits_the_spread(self):
        row = _averages_from_grades(self._grades([4, 6, 7.4]), {})[0]
        self.assertTrue(row["below"])
        self.assertTrue(row["near_cut"])  # 5,8 com notas espalhadas: o lado depende de uma nota
        far = _averages_from_grades(self._grades([2, 2.5, 3]), {})[0]
        self.assertFalse(far["near_cut"])
        two = _averages_from_grades(self._grades([5, 6.5]), {})[0]
        self.assertIsNone(two["se"])
        AcademicRule.objects.create(school=self.school, subject=self.mat, formula=AcademicRule.Formula.BEST)
        from apps.analytics.services import rules_by_subject

        best = _averages_from_grades(self._grades([4, 6, 7.4]), rules_by_subject(self.school))[0]
        self.assertFalse(best["near_cut"])


class PollMarginTests(CommunicationBase):
    def test_margin_tie_and_low_response(self):
        rows, margin = poll_margins([40, 35, 5], audience=200)
        self.assertTrue(margin["tie"])
        self.assertTrue(margin["low_response"])
        self.assertLess(rows[0]["low"], 50)
        rows, margin = poll_margins([90, 10], audience=100)
        self.assertEqual((rows[0]["low"], rows[0]["high"]), (90, 90))  # todas responderam: sem margem de acaso
        self.assertFalse(margin["tie"])

    def test_staff_sees_margin_family_does_not(self):
        poll = Poll.objects.create(school=self.school, question="Reunião?", options=["Terça", "Sábado"],
                                   created_by=self.direc, deadline=timezone.localdate() + dt.timedelta(days=5))
        PollVote.objects.create(poll=poll, user=self.resp, option=0)
        self.login("dir")
        page = self.client.get(reverse("communication:poll_detail", args=[poll.pk]))
        self.assertContains(page, "IC 95%")
        self.login("resp")
        page = self.client.get(reverse("communication:poll_detail", args=[poll.pk]))
        self.assertNotContains(page, "IC 95%")


class AttendanceControlTests(CommunicationBase):
    def setUp(self):
        super().setUp()
        today = timezone.localdate()
        SchoolYear.objects.filter(pk=self.year.pk).update(is_current=True, start_date=today - dt.timedelta(days=90),
                                                          end_date=today + dt.timedelta(days=60))
        kids = [Student.objects.create(school=self.school, first_name=f"S{i}") for i in range(20)]
        for k in kids:
            Enrollment.objects.create(school=self.school, student=k, class_group=self.turma, school_year=self.year)
        monday = today - dt.timedelta(days=today.weekday()) - dt.timedelta(weeks=10)
        records = []
        for w in range(10):
            for day in range(5):
                d = monday + dt.timedelta(weeks=w, days=day)
                absent = 12 if w == 6 else (1 if (w + day) % 2 else 2)  # semana 6: surto
                for i, k in enumerate(kids):
                    records.append(AttendanceRecord(school=self.school, class_group=self.turma, student=k, date=d,
                                                    status="ausente" if i < absent else "presente"))
        AttendanceRecord.objects.bulk_create(records)
        self.bad_week = monday + dt.timedelta(weeks=6)

    def test_special_cause_week_is_found(self):
        today = timezone.localdate()
        res = spc.control(self.school, today - dt.timedelta(days=90), today)
        self.assertTrue(res["enough"])
        self.assertEqual([p["label"] for p in res["signals"]], [self.bad_week])
        # Semana com chamada quase toda não lançada: fora da carta, listada à parte (não vira "queda").
        last = self.bad_week + dt.timedelta(weeks=4)
        AttendanceRecord.objects.create(school=self.school, class_group=self.turma, date=last, status="ausente",
                                        student=Student.objects.filter(first_name="S0").get())
        res = spc.control(self.school, today - dt.timedelta(days=90), today + dt.timedelta(days=30))
        self.assertEqual([w["label"] for w in res["sparse"]], [last])
        self.assertEqual([p["label"] for p in res["signals"]], [self.bad_week])

    def test_access(self):
        url = reverse("analytics:attendance_control")
        self.login("dir")
        page = self.client.get(url)
        self.assertContains(page, "Escola toda")
        self.assertContains(page, self.bad_week.strftime("%d/%m/%Y"))
        self.login("prof")
        page = self.client.get(url)
        self.assertEqual(page.context["chosen"], self.turma)  # professor vê a turma dele
        self.assertEqual(self.client.get(url, {"turma": self.turma_b.pk}).status_code, 404)
        self.login("resp")
        self.assertEqual(self.client.get(url).status_code, 403)
