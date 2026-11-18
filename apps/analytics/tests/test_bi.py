"""Cálculos dos painéis de BI conferidos com valores feitos à mão.

O Prompt 13 (§15) exige que os cálculos sejam confrontados com consultas de
referência. Cada teste monta poucos registros, calcula o resultado esperado
"no papel" e compara com o motor (``bi.py``).
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.core.models import Role, School, User
from apps.pedagogy.models import (
    AbsenceJustification,
    AcademicRule,
    Activity,
    AttendanceRecord,
    Evaluation,
    Grade,
    InterventionPlan,
    SchoolConfig,
    Submission,
)
from apps.registry.models import Enrollment, Student

from .. import bi

PW = "senha-forte-1"
# Período fixo para os testes não dependerem do dia em que rodam.
P = bi.Period(date(2026, 3, 1), date(2026, 6, 30), "personalizado", "teste")


class BIBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        self.year = SchoolYear.objects.create(
            school=self.school, name="2026", start_date=date(2026, 2, 1),
            end_date=date(2026, 12, 15), is_current=True,
        )
        self.turma = ClassGroup.objects.create(school=self.school, school_year=self.year, name="5º A")
        self.mat = Subject.objects.create(school=self.school, name="Matemática")
        self.por = Subject.objects.create(school=self.school, name="Português")
        self.prof = User.objects.create_user(username="prof", password=PW, role=Role.PROFESSOR, school=self.school)
        TeacherAssignment.objects.create(school=self.school, school_year=self.year, teacher=self.prof,
                                         class_group=self.turma, subject=self.mat)
        SchoolConfig.objects.create(school=self.school, max_absences_percent=Decimal("25"))
        self.alunos = []
        for nome in ("Ana", "Bia", "Caio", "Davi", "Eva", "Fábio"):
            s = Student.objects.create(school=self.school, first_name=nome)
            Enrollment.objects.create(school=self.school, student=s, class_group=self.turma,
                                      school_year=self.year, started_on=date(2026, 2, 1))
            self.alunos.append(s)
        self.ana = self.alunos[0]

    def evaluation(self, subject, d, weight="1", title=None, kind=""):
        return Evaluation.objects.create(
            school=self.school, subject=subject, class_group=self.turma, title=title or f"Prova {d}",
            weight=Decimal(weight), date=d, status=Evaluation.Status.PUBLISHED, created_by=self.prof, kind=kind,
        )

    def grade(self, ev, student, value):
        return Grade.objects.create(school=self.school, evaluation=ev, student=student,
                                    value=None if value is None else Decimal(str(value)))

    def attend(self, student, d, status):
        AttendanceRecord.objects.create(school=self.school, class_group=self.turma, student=student,
                                        date=d, status=status)


class AcademicTests(BIBase):
    def test_weighted_subject_average_and_overall(self):
        AcademicRule.objects.create(school=self.school, subject=self.mat,
                                    formula=AcademicRule.Formula.WEIGHTED, passing_grade=Decimal("6"))
        e1 = self.evaluation(self.mat, date(2026, 3, 10), weight="1")
        e2 = self.evaluation(self.mat, date(2026, 4, 10), weight="3")
        e3 = self.evaluation(self.por, date(2026, 4, 12))
        self.grade(e1, self.ana, 4)
        self.grade(e2, self.ana, 8)   # ponderada: (4*1 + 8*3) / 4 = 7,0
        self.grade(e3, self.ana, 5)   # aritmética: 5,0 (abaixo de 6)
        r = bi.student_report(self.ana, P)
        subj = {s["subject"].name: s for s in r["academic"]["subjects"]}
        self.assertEqual(subj["Matemática"]["average"], 7.0)
        self.assertEqual(subj["Português"]["average"], 5.0)
        self.assertTrue(subj["Português"]["below"])
        self.assertEqual(r["academic"]["overall"], 6.0)   # (7 + 5) / 2
        self.assertEqual(r["academic"]["n_grades"], 3)

    def test_blank_grade_is_not_zero(self):
        e = self.evaluation(self.mat, date(2026, 3, 10))
        self.grade(e, self.ana, None)
        r = bi.student_report(self.ana, P)
        self.assertIsNone(r["academic"]["overall"])
        self.assertEqual(r["academic"]["subjects"], [])

    def test_draft_and_out_of_period_do_not_count(self):
        dentro = self.evaluation(self.mat, date(2026, 3, 10))
        fora = self.evaluation(self.mat, date(2026, 8, 10))
        rasc = self.evaluation(self.mat, date(2026, 3, 11))
        rasc.status = Evaluation.Status.DRAFT
        rasc.save()
        self.grade(dentro, self.ana, 8)
        self.grade(fora, self.ana, 2)
        self.grade(rasc, self.ana, 2)
        r = bi.student_report(self.ana, P)
        self.assertEqual(r["academic"]["overall"], 8.0)

    def test_delta_against_previous_period(self):
        prev = P.previous()
        self.assertEqual(prev.end, date(2026, 2, 28))
        self.assertEqual(prev.days, P.days)
        for d, v in ((prev.end - timedelta(days=5), 4), (prev.end - timedelta(days=3), 4)):
            self.grade(self.evaluation(self.mat, d), self.ana, v)
        for d, v in ((date(2026, 3, 5), 7), (date(2026, 3, 9), 7)):
            self.grade(self.evaluation(self.mat, d), self.ana, v)
        r = bi.student_report(self.ana, P)
        mat = r["academic"]["subjects"][0]
        self.assertEqual(mat["delta"], 3.0)
        titulos = [i["title"] for i in r["insights"]]
        self.assertIn("Matemática: melhora em relação ao período anterior", titulos)

    def test_trend_requires_enough_points(self):
        self.assertEqual(bi.trend([(date(2026, 3, 1), 5)])["direction"], "insuficiente")
        pts = [(date(2026, 3, 1), 4), (date(2026, 4, 1), 5), (date(2026, 5, 1), 6), (date(2026, 6, 1), 7)]
        t = bi.trend(pts)
        self.assertEqual(t["direction"], "alta")
        self.assertAlmostEqual(t["slope"], 0.99, delta=0.05)  # ~1 ponto por mês

    def test_describe_reference_values(self):
        d = bi.describe([2, 4, 4, 4, 5, 5, 7, 9])
        self.assertEqual((d["mean"], d["median"], d["stdev"], d["min"], d["max"]), (5.0, 4.5, 2.0, 2.0, 9.0))
        self.assertIsNone(bi.describe([5, 6])["stdev"])  # menos de 3 valores

    def test_class_mean_is_mean_of_student_means_even_with_best_rule(self):
        """Com "melhor nota", a média da turma não pode virar a maior nota da turma."""
        AcademicRule.objects.create(school=self.school, subject=self.mat,
                                    formula=AcademicRule.Formula.BEST, passing_grade=Decimal("6"))
        e1 = self.evaluation(self.mat, date(2026, 3, 10))
        e2 = self.evaluation(self.mat, date(2026, 4, 10))
        notas = [(3, 5), (6, 4), (7, 7), (2, 9), (5, 5), (8, 6)]  # melhores: 5,6,7,9,5,8
        for s, (a, b) in zip(self.alunos, notas):
            self.grade(e1, s, a)
            self.grade(e2, s, b)
        r = bi.class_report(self.turma, P)
        mat = r["subject_summary"][0]
        self.assertEqual(mat["mean"], round((5 + 6 + 7 + 9 + 5 + 8) / 6, 2))  # 6,67, não 9
        self.assertEqual(mat["below_count"], 2)  # 5 e 5

    def test_class_comparison_hidden_for_small_group(self):
        e = self.evaluation(self.mat, date(2026, 3, 10))
        for s in self.alunos[:3]:   # só 3 estudantes com nota
            self.grade(e, s, 7)
        r = bi.student_report(self.ana, P, show_class_comparison=True)
        self.assertIsNone(r["academic"]["subjects"][0]["class_mean"])
        for s in self.alunos[3:]:
            self.grade(e, s, 5)
        r = bi.student_report(self.ana, P, show_class_comparison=True)
        self.assertEqual(r["academic"]["subjects"][0]["class_mean"], 6.0)  # (3×7 + 3×5) / 6

    def test_recovery_marked_evaluation(self):
        self.grade(self.evaluation(self.mat, date(2026, 3, 10)), self.ana, 4)
        self.grade(self.evaluation(self.mat, date(2026, 3, 20), kind=Evaluation.Kind.RECOVERY), self.ana, 7)
        rec = bi.student_report(self.ana, P)["academic"]["recovery"]
        self.assertEqual(len(rec), 1)
        self.assertEqual((rec[0]["before"], rec[0]["value"], rec[0]["reached"]), (4.0, 7.0, True))


class AttendanceTests(BIBase):
    def test_counts_percent_justified_streak(self):
        dias = [date(2026, 3, 2) + timedelta(days=i) for i in range(10)]  # 2 a 11/03
        status = ["presente", "atraso", "falta", "falta", "falta", "presente", "presente",
                  "presente", "falta", "presente"]
        for d, s in zip(dias, status):
            self.attend(self.ana, d, s)
        AbsenceJustification.objects.create(
            school=self.school, student=self.ana, class_group=self.turma,
            start_date=date(2026, 3, 4), end_date=date(2026, 3, 5), reason="médico",
            status=AbsenceJustification.Status.APPROVED,
        )
        AbsenceJustification.objects.create(  # recusada não conta
            school=self.school, student=self.ana, class_group=self.turma,
            start_date=date(2026, 3, 10), end_date=date(2026, 3, 10), reason="x",
            status=AbsenceJustification.Status.REFUSED,
        )
        a = bi.student_report(self.ana, P)["attendance"]
        self.assertEqual((a["total"], a["present"], a["late"], a["absent"]), (10, 5, 1, 4))
        self.assertEqual(a["percent"], 60.0)          # (5 + 1) / 10
        self.assertEqual(a["absence_percent"], 40.0)
        self.assertEqual(a["limit_level"], "acima")   # 40% ≥ 25%
        self.assertEqual((a["justified"], a["unjustified"]), (2, 2))
        self.assertEqual(a["streak"]["length"], 3)
        self.assertEqual(a["streak"]["start"], date(2026, 3, 4))
        self.assertEqual(len(a["by_weekday"]), 7)     # 10 registros: exibido

    def test_no_records_is_none_not_zero(self):
        a = bi.student_report(self.ana, P)["attendance"]
        self.assertIsNone(a["percent"])
        self.assertIsNone(a["limit_level"])
        self.assertEqual(a["by_weekday"], [])

    def test_near_limit_level(self):
        # 21 registros, 5 faltas = 23,8%: ≥ 80% de 25 (20) e < 25 → "perto"
        for i in range(21):
            self.attend(self.ana, date(2026, 3, 2) + timedelta(days=i), "falta" if i < 5 else "presente")
        self.assertEqual(bi.student_report(self.ana, P)["attendance"]["limit_level"], "perto")


    def test_period_signal_comes_with_the_school_year_situation(self):
        # 4 faltas em 10 dias com chamada: o sinal do período diz "acima", mas no ano letivo (sem calendário
        # publicado, 200 dias da LDB × 25% = 50 permitidas) ainda cabem 46. O painel mostra os dois, sem contradizer
        # a Agenda e faltas.
        for i in range(10):
            self.attend(self.ana, date(2026, 3, 2) + timedelta(days=i), "falta" if i < 4 else "presente")
        r = bi.student_report(self.ana, P)
        a = r["attendance"]
        self.assertEqual(a["limit_level"], "acima")
        self.assertEqual((a["year_outlook"]["allowed"], a["year_outlook"]["left"]), (50, 46))
        self.assertIn("No ano letivo: 4 de 50 falta(s) permitida(s)", a["year_outlook"]["sentence"])
        self.assertIn("ainda cabem 46", a["year_outlook"]["sentence"])
        insight = next(i for i in r["insights"] if "limite" in i["title"])
        self.assertEqual(insight["title"], "Faltas do período acima do limite da escola")
        self.assertIn("ainda cabem 46", insight["observed"])

    def test_no_signal_no_extra_queries_for_the_year(self):
        self.assertIsNone(bi.student_report(self.ana, P)["attendance"]["year_outlook"])

class ActivityTests(BIBase):
    def act(self, deadline, title):
        return Activity.objects.create(
            school=self.school, class_group=self.turma, subject=self.mat, title=title,
            created_by=self.prof, published_date=date(2026, 3, 1), deadline=deadline,
            status=Activity.Status.PUBLISHED,
        )

    def test_five_states_and_rates(self):
        S = Submission.Status
        passado = date(2026, 3, 20)
        estados = [S.DELIVERED, S.DELIVERED, S.LATE, S.NOT_DELIVERED]
        for i, st in enumerate(estados):
            a = self.act(passado, f"A{i}")
            Submission.objects.create(school=self.school, activity=a, student=self.ana, status=st)
        self.act(passado, "Sem registro")
        futuro = date.today() + timedelta(days=30)
        p = bi.Period(date(2026, 3, 1), futuro, "personalizado", "x")
        self.act(futuro, "Em aberto")
        cancelada = self.act(passado, "Cancelada")
        cancelada.status = Activity.Status.CANCELED
        cancelada.save()
        a = bi.student_report(self.ana, p)["activities"]
        self.assertEqual(a["proposed"], 6)  # cancelada fora
        self.assertEqual((a["on_time"], a["late"], a["not_delivered"], a["no_record"], a["open"]), (2, 1, 1, 1, 1))
        self.assertEqual(a["delivery_rate"], 75.0)   # 3 entregues / 4 registradas
        self.assertEqual(a["coverage"], 80.0)        # 4 registradas / 5 vencidas
        self.assertEqual(a["on_time_rate"], 66.7)    # 2 no prazo / 3 entregues

    def test_activity_before_student_joined_does_not_reach_him(self):
        tarde = Student.objects.create(school=self.school, first_name="Gil")
        Enrollment.objects.create(school=self.school, student=tarde, class_group=self.turma,
                                  school_year=self.year, started_on=date(2026, 5, 1))
        self.act(date(2026, 3, 20), "Antes da entrada")
        self.assertEqual(bi.student_report(tarde, P)["activities"]["proposed"], 0)


class ClassMatrixTests(BIBase):
    def test_follow_up_criteria_and_evolution(self):
        e1 = self.evaluation(self.mat, date(2026, 3, 10))   # 1ª metade
        e2 = self.evaluation(self.mat, date(2026, 6, 10))   # 2ª metade
        for s in self.alunos:
            self.grade(e1, s, 7)
            self.grade(e2, s, 7)
        Grade.objects.filter(evaluation=e1, student=self.ana).update(value=3)
        Grade.objects.filter(evaluation=e2, student=self.ana).update(value=5)  # média 4 (abaixo); evolução +2
        r = bi.class_report(self.turma, P)
        ana = next(x for x in r["rows"] if x["student"] == self.ana)
        self.assertEqual(ana["overall"], 4.0)
        self.assertEqual(ana["evolution"], 2.0)
        self.assertEqual(len(r["follow_up"]), 1)
        self.assertEqual(r["evolved"], 1)
        self.assertEqual(r["active"], 6)
        r2 = bi.class_report(self.turma, P, min_subjects_below=2)  # critério ajustado
        self.assertEqual(len(r2["follow_up"]), 0)

    def test_decision_reliability_flags_near_cut(self):
        # Ana: 5,9 / 6,0 / 6,1 → média 6,0, bem no corte (decisão frágil).
        # Bia: 9 / 9 / 9 → média 9,0, longe do corte (avaliável, não frágil).
        # Caio: só 1 nota → erro-padrão não calculável, fora do denominador.
        days = [date(2026, 3, 10), date(2026, 4, 10), date(2026, 5, 10)]
        evs = [self.evaluation(self.mat, d) for d in days]
        for e, v in zip(evs, ("5.9", "6.0", "6.1")):
            self.grade(e, self.ana, v)
        for e in evs:
            self.grade(e, self.alunos[1], 9)   # Bia
        self.grade(evs[0], self.alunos[2], 6)  # Caio, nota única
        dr = bi.class_report(self.turma, P)["decision_reliability"]
        self.assertEqual((dr["assessable"], dr["fragile"], dr["share"]), (2, 1, 50.0))
        self.assertEqual(len(dr["rows"]), 1)
        row = dr["rows"][0]
        self.assertEqual((row["student"], row["subject"], row["below"], row["count"], row["gap"]),
                         (self.ana, self.mat, False, 3, 0.0))

    def test_grade_comparability_person_centered(self):
        # 5 estudantes, Matemática sempre 1 ponto acima de Português para o mesmo estudante.
        # Cada estudante: desvio_mat = +0,5 e desvio_por = −0,5 → desvio médio mat +0,5, por −0,5.
        em = self.evaluation(self.mat, date(2026, 3, 10))
        ep = self.evaluation(self.por, date(2026, 3, 11))
        for s, por in zip(self.alunos[:5], (5, 5, 5, 6, 6)):
            self.grade(ep, s, por)
            self.grade(em, s, por + 1)
        # Fábio só tem Português (1 disciplina) → fora da comparação (min_subjects=2).
        self.grade(ep, self.alunos[5], 7)
        gc = bi.class_report(self.turma, P)["grade_comparability"]
        self.assertTrue(gc["enough"])
        rows = {row["subject"]: row for row in gc["subjects"]}
        self.assertEqual((rows[self.mat]["mean_dev"], rows[self.mat]["n"]), (0.5, 5))
        self.assertEqual((rows[self.por]["mean_dev"], rows[self.por]["n"]), (-0.5, 5))
        self.assertEqual(gc["subjects"][0]["subject"], self.mat)  # mais branda no topo

    def test_grade_comparability_only_full_view(self):
        em = self.evaluation(self.mat, date(2026, 3, 10))
        for s in self.alunos:
            self.grade(em, s, 7)
        # Visão limitada a uma disciplina (professor) não calcula comparabilidade.
        self.assertIsNone(bi.class_report(self.turma, P, only_subjects={self.mat.pk})["grade_comparability"])

    def test_approval_rate_with_wilson_interval(self):
        from apps.core.stats import wilson

        e = self.evaluation(self.mat, date(2026, 3, 10))
        for s, v in zip(self.alunos[:4], (8, 7, 6, 3)):  # 3 aprovados (>=6), 1 abaixo → 75%
            self.grade(e, s, v)
        summary = {s["subject"]: s for s in bi.class_report(self.turma, P)["subject_summary"]}
        ap = summary[self.mat]["approval"]
        p, lo, hi = wilson(3, 4)
        self.assertEqual((ap["approved"], ap["n"], ap["rate"]), (3, 4, round(p * 100, 1)))
        self.assertEqual((ap["low"], ap["high"]), (round(lo * 100, 1), round(hi * 100, 1)))
        self.assertLess(ap["low"], 75.0)  # intervalo largo com poucos estudantes
        self.assertGreater(ap["high"], 75.0)

    def test_evaluation_outliers_tukey(self):
        # 8 notas agrupadas em ~7 e uma em 1 → a nota 1 cai fora da cerca inferior de Tukey.
        e = self.evaluation(self.mat, date(2026, 3, 10))
        for i in range(8):
            st = Student.objects.create(school=self.school, first_name=f"Aluno{i}")
            Enrollment.objects.create(school=self.school, student=st, class_group=self.turma, school_year=self.year)
            self.grade(e, st, 7 if i else 1)  # o primeiro recebe 1
        row = next(x for x in bi.class_report(self.turma, P)["evaluations"] if x["evaluation"] == e)
        self.assertIsNotNone(row["outliers"])
        self.assertGreaterEqual(row["outliers"]["n_low"], 1)
        self.assertEqual(row["outliers"]["n_high"], 0)

    def test_freq_performance_association(self):
        att, rows = {}, {}
        for sid in range(24):  # 12 freq baixa+abaixo, 12 freq ok+ok → associação perfeita
            low = sid < 12
            att[sid] = [5, 10] if low else [9, 10]  # 50% vs 90% (mínimo da escola = 75%)
            rows[sid] = {1: {"average": 5.0 if low else 7.0, "below": low}}
        fp = bi._freq_performance(list(range(24)), att, rows, limit=25)
        self.assertEqual(fp["table"], [[12, 0], [0, 12]])
        self.assertTrue(fp["enough"])
        self.assertEqual(fp["cramers_v"], 1.0)
        self.assertLess(fp["p"], 0.01)

    def test_freq_performance_insufficient(self):
        fp = bi._freq_performance([0], {0: [5, 10]}, {0: {1: {"average": 5.0, "below": True}}}, limit=25)
        self.assertFalse(fp["enough"])
        self.assertIsNone(fp["cramers_v"])

    def test_evaluation_missing_grades(self):
        e = self.evaluation(self.mat, date(2026, 3, 10))
        for s in self.alunos[:4]:
            self.grade(e, s, 6)
        row = bi.class_report(self.turma, P)["evaluations"][0]
        self.assertEqual((row["n"], row["missing"]), (4, 2))

    def test_query_budget_does_not_grow_with_students(self):
        e = self.evaluation(self.mat, date(2026, 3, 10))
        for s in self.alunos:
            self.grade(e, s, 6)
            self.attend(s, date(2026, 3, 10), "presente")
        with CaptureQueriesContext(connection) as poucos:
            bi.class_report(self.turma, P)
        for i in range(20):
            s = Student.objects.create(school=self.school, first_name=f"X{i}")
            Enrollment.objects.create(school=self.school, student=s, class_group=self.turma, school_year=self.year)
            self.grade(e, s, 5)
            self.attend(s, date(2026, 3, 10), "falta")
        with CaptureQueriesContext(connection) as muitos:
            bi.class_report(self.turma, P)
        self.assertEqual(len(poucos), len(muitos))


class PreloadTests(BIBase):
    """Painel da coordenação: várias turmas em consultas fixas, com o mesmo resultado de class_report."""

    def summary(self, r):
        return (r["active"], r["overall"], r["attendance"], r["delivery_rate"], r["monthly"],
                [(x["student"].pk, x["overall"], x["attendance"]["percent"], x["delivery_rate"], tuple(x["reasons"]))
                 for x in r["rows"]],
                [(e["evaluation"].pk, e["mean"], e["missing"]) for e in r["evaluations"]])

    def test_preloaded_reports_match_and_do_not_query_per_class(self):
        turma_b = ClassGroup.objects.create(school=self.school, school_year=self.year, name="5º B")
        movida = self.alunos[5]
        Enrollment.objects.filter(student=movida).update(status="transferido")
        Enrollment.objects.create(school=self.school, student=movida, class_group=turma_b, school_year=self.year)
        e_a = self.evaluation(self.mat, date(2026, 3, 10))
        e_b = Evaluation.objects.create(school=self.school, subject=self.por, class_group=turma_b, title="B1",
                                        weight=Decimal("2"), date=date(2026, 4, 2), status=Evaluation.Status.PUBLISHED,
                                        created_by=self.prof)
        for i, s in enumerate(self.alunos):
            self.grade(e_a, s, 4 + i)
            self.attend(s, date(2026, 3, 10), "falta" if i % 3 == 0 else "presente")
        self.grade(e_b, movida, 8)
        AttendanceRecord.objects.create(school=self.school, class_group=turma_b, student=movida, date=date(2026, 4, 2),
                                        status="atraso")
        act = Activity.objects.create(school=self.school, class_group=self.turma, subject=self.mat, title="Lista",
                                      created_by=self.prof, status=Activity.Status.PUBLISHED,
                                      published_date=date(2026, 3, 1), deadline=date(2026, 3, 20))
        Submission.objects.create(school=self.school, activity=act, student=self.ana, status="entregue")
        classes = [self.turma, turma_b]
        with CaptureQueriesContext(connection) as queries:
            pre = bi.preload_classes(classes, P)
            batched = [bi.class_report(cg, P, preload=pre) for cg in classes]
        for cg, r in zip(classes, batched):
            self.assertEqual(self.summary(r), self.summary(bi.class_report(cg, P)), cg.name)
        self.assertEqual(batched[1]["rows"][0]["student"], movida)
        self.assertLessEqual(len(queries), 12)  # 7 de carga + regras da escola, independente do número de turmas


class InstitutionalAndQualityTests(BIBase):
    def test_small_groups_are_hidden_in_comparisons(self):
        pequena = ClassGroup.objects.create(school=self.school, school_year=self.year, name="Reforço")
        s = Student.objects.create(school=self.school, first_name="Só")
        Enrollment.objects.create(school=self.school, student=s, class_group=pequena, school_year=self.year)
        r = bi.institutional_report(self.school, P)
        row = next(c for c in r["classes"] if c["class_group"] == pequena)
        self.assertTrue(row["small"])
        self.assertIsNone(row["average"])
        self.assertIsNone(row["attendance"])

    def test_quality_detects_missing_grades_and_partial_attendance(self):
        e = self.evaluation(self.mat, date(2026, 3, 10))
        self.grade(e, self.ana, 7)
        self.attend(self.ana, date(2026, 3, 10), "presente")  # 1 de 6 na chamada
        q = bi.data_quality(self.school, P)
        self.assertEqual(q["missing_grades"][0]["missing"], 5)
        self.assertEqual(q["partial_days"][0]["missing"], 5)
        self.assertGreaterEqual(q["without_guardian"].count(), 6)

    def test_intervention_before_after(self):
        plano = InterventionPlan.objects.create(school=self.school, student=self.ana, title="Reforço")
        pivot = plano.created_at.date()
        for dias, v in ((-30, 4), (-20, 5)):
            self.grade(self.evaluation(self.mat, pivot + timedelta(days=dias)), self.ana, v)
        r = bi._interventions(self.ana, date.today())
        self.assertEqual(r[0]["grade_before"], 4.5)
        self.assertIsNone(r[0]["grade_after"])   # sem 2 notas depois: não compara
        self.assertIsNone(r[0]["delta"])


class PeriodTests(BIBase):
    def test_presets_and_invalid_custom(self):
        self.assertEqual(bi.resolve_period({}, self.school).start, date(2026, 2, 1))
        p = bi.resolve_period({"periodo": "personalizado", "inicio": "2026-05-01", "fim": "2026-04-01"}, self.school)
        self.assertEqual(p.preset, "ano")   # invertido: volta ao padrão
        p = bi.resolve_period({"periodo": "personalizado", "inicio": "2026-04-01", "fim": "2026-04-30"}, self.school)
        self.assertEqual((p.start, p.end, p.days), (date(2026, 4, 1), date(2026, 4, 30), 30))
        self.assertEqual(bi.resolve_period({"periodo": "30d"}, self.school).days, 30)


class NPlusOneGuardTests(BIBase):
    """O painel da turma carrega notas, frequencia e entregas em lote: o numero
    de consultas nao pode crescer com o numero de estudantes (sem N+1)."""

    def _populate(self, ev, att_day, students):
        for s in students:
            self.grade(ev, s, 7)
            self.attend(s, att_day, AttendanceRecord.Status.PRESENT)

    def test_class_report_query_count_is_independent_of_student_count(self):
        ev = self.evaluation(self.mat, date(2026, 3, 10))
        att_day = date(2026, 3, 3)
        self._populate(ev, att_day, self.alunos)  # 6 estudantes
        with CaptureQueriesContext(connection) as q_small:
            bi.class_report(self.turma, P)
        extra = []
        for nome in ("Gil", "Hugo", "Ivo", "Joy", "Kim", "Lia"):
            s = Student.objects.create(school=self.school, first_name=nome)
            Enrollment.objects.create(school=self.school, student=s, class_group=self.turma,
                                      school_year=self.year, started_on=date(2026, 2, 1))
            extra.append(s)
        self._populate(ev, att_day, extra)  # agora 12 estudantes
        with CaptureQueriesContext(connection) as q_big:
            bi.class_report(self.turma, P)
        self.assertEqual(
            len(q_small.captured_queries), len(q_big.captured_queries),
            f"N+1 no painel da turma: {len(q_small.captured_queries)} -> "
            f"{len(q_big.captured_queries)} consultas ao dobrar os estudantes")
