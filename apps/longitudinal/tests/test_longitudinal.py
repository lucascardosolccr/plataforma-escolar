"""Trajetória escolar: anos anteriores, diagnóstico, análises da escola, previsão validada e acesso."""

import datetime as dt
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear
from apps.cognitio.models import ModelRun
from apps.communication.tests.test_communication import CommunicationBase
from apps.coordination.models import CoordinatorAssignment
from apps.core.models import AuditLog, Role, User
from apps.pedagogy.models import Evaluation, Grade
from apps.registry.models import Enrollment, Student

from .. import cohort, diagnosis, forecast, stages, stats
from .. import timeline as tl
from ..models import Outcome, PriorGrade, PriorYear, YearResult


class Base(CommunicationBase):
    def setUp(self):
        super().setUp()
        today = timezone.localdate()
        SchoolYear.objects.filter(pk=self.year.pk).update(
            is_current=True, start_date=today - dt.timedelta(days=200), end_date=today + dt.timedelta(days=30))
        self.year.refresh_from_db()
        self.ana.birth_date = dt.date(2018, 1, 10)  # 8 anos em 31/03/2026 no 1º ano: distorção de 2 anos
        self.ana.code = "A1"
        self.ana.save()

    def prior(self, student, year, grade, outcome=Outcome.UNKNOWN, attendance=None, school="EC Outra", **grades):
        p = PriorYear.objects.create(school=self.school, student=student, year=year, grade_label=grade,
                                     stage=stages.parse_stage(grade), school_name=school, outcome=outcome,
                                     attendance_percent=attendance)
        for subject, value in grades.items():
            PriorGrade.objects.create(record=p, subject=subject, value=Decimal(str(value)))
        return p

    def ana_history(self):
        self.prior(self.ana, 2024, "1º ano", Portugues=5.0, Matematica=7.0)
        self.prior(self.ana, 2025, "1º ano", Outcome.RETAINED, Decimal("85.0"), Portugues=4.5, Matematica=6.5)


class TimelineAndDiagnosisTests(Base):
    def test_years_are_merged_and_outcomes_say_where_they_came_from(self):
        self.ana_history()
        rows = tl.build(self.ana)
        self.assertEqual([r["year"] for r in rows], [2024, 2025, 2026])
        self.assertEqual((rows[0]["outcome"], rows[0]["basis"]), (Outcome.RETAINED, "deduzido"))  # repetiu o 1º ano
        self.assertEqual((rows[1]["outcome"], rows[1]["basis"]), (Outcome.RETAINED, "oficial"))
        self.assertEqual(rows[2]["basis"], "cursando")
        self.assertEqual(rows[2]["distortion"], 2)
        self.assertEqual(rows[2]["retentions_before"], 2)
        self.assertEqual(rows[1]["subjects"][1]["key"], "Língua Portuguesa")  # "Portugues" vira o componente
        keys = {f.key for f in diagnosis.diagnose(rows)}
        self.assertTrue({"retencao", "distorcao", "frequencia", "persistente", "resultado_deduzido"} <= keys)
        self.assertNotIn("mobilidade", keys)  # uma troca de escola só
        persistent = next(f for f in diagnosis.diagnose(rows) if f.key == "persistente")
        self.assertIn("Língua Portuguesa", persistent.title)
        self.prior(self.ana, 2023, "Pré II", Portugues=4, Matematica=4, Arte=4)
        PriorGrade.objects.create(record=PriorYear.objects.get(year=2024), subject="Matemática", value=Decimal("4"))
        PriorGrade.objects.filter(record__year=2024, subject="Matematica").delete()
        PriorGrade.objects.create(record=PriorYear.objects.get(year=2024), subject="Arte", value=Decimal("3"))
        found = diagnosis.diagnose(tl.build(self.ana))
        merged = next(f for f in found if f.key == "persistente_geral")  # 3 componentes: um achado só
        self.assertIn("3 componentes", merged.title)
        self.assertFalse(any(f.key == "persistente" for f in found))

    def test_official_result_beats_deduction_and_drop_respects_class_position(self):
        self.prior(self.ana, 2025, "1º ano", Outcome.APPROVED, Portugues=9.0, Matematica=9.0)
        self.prior(self.ana, 2024, "1º ano", Portugues=8, Matematica=8)  # ano seguinte no mesmo ano: retido deduzido
        rows = tl.build(self.ana)
        self.assertEqual(rows[0]["outcome"], Outcome.RETAINED)
        e = Enrollment.objects.get(student=self.ana)
        YearResult.objects.create(school=self.school, enrollment=e, outcome=Outcome.APPROVED)
        SchoolYear.objects.filter(pk=self.year.pk).update(end_date=timezone.localdate() - dt.timedelta(days=1),
                                                          is_current=False)
        rows = tl.build(self.ana)
        self.assertEqual((rows[-1]["outcome"], rows[-1]["basis"]), (Outcome.APPROVED, "oficial"))

    def test_stages_and_reference_age(self):
        cases = {"1º ano": 1, "3o Ano A": 3, "9º ano EF": 9, "1ª série EM": 10, "2ª série do ensino médio": 11,
                 "Pré II": None, "": None}
        self.assertEqual({k: stages.parse_stage(k) for k in cases}, cases)
        self.assertEqual(stages.age_on_cutoff(dt.date(2019, 3, 31), 2025), 6)  # faz 6 no dia do corte
        self.assertEqual(stages.age_on_cutoff(dt.date(2019, 4, 1), 2025), 5)
        self.assertEqual(stages.distortion(dt.date(2015, 1, 1), 2025, 4), 1)
        self.assertIsNone(stages.distortion(None, 2025, 4))

    def test_needed_grade_in_the_current_year(self):
        ev = Evaluation.objects.create(school=self.school, subject=self.mat, class_group=self.turma, title="P1",
                                       status=Evaluation.Status.PUBLISHED, date=timezone.localdate())
        Grade.objects.create(school=self.school, evaluation=ev, student=self.ana, value=Decimal("4.0"))
        cur = tl.build(self.ana)[-1]
        need = tl.needed_grades(cur)
        self.assertEqual(len(need), 1)
        done = need[0]["done"]
        self.assertAlmostEqual(need[0]["need"], round((6 - 4 * done) / (1 - done), 1))
        self.assertEqual(need[0]["status"], "impossivel")


class AccessTests(Base):
    def test_who_sees_what(self):
        self.ana_history()
        url = reverse("longitudinal:student", args=[self.ana.pk])
        for user, code in (("dir", 200), ("coord", 200), ("sec", 200), ("resp", 200), ("adm", 200), ("prof", 403),
                           ("resp_b", 404)):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, code, user)
        for user, sees in (("dir", True), ("coord", True), ("sec", False), ("resp", False), ("adm", False)):
            self.login(user)
            page = self.client.get(url).content.decode()
            self.assertEqual("Diagnóstico da trajetória" in page, sees, user)
            self.assertEqual("Previsão para o ano" in page, sees, user)
            self.assertIn("EC Outra", page)
        self.assertTrue(AuditLog.objects.filter(action="view", detail__contains="trajetória escolar").exists())

    def test_index_by_profile(self):
        self.ana_history()
        url = reverse("longitudinal:index")
        self.login("dir")
        page = self.client.get(url)
        self.assertContains(page, "Começo de ano")
        self.assertContains(page, "Ana")
        self.login("sec")
        page = self.client.get(url)
        self.assertContains(page, "Como lançar")
        self.assertNotContains(page, "Começo de ano")
        self.login("resp")
        self.assertContains(self.client.get(url), reverse("longitudinal:student", args=[self.ana.pk]))
        self.login("prof")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login("dir")
        csv_resp = self.client.get(reverse("longitudinal:export"))
        self.assertIn("Ana", csv_resp.content.decode("utf-8"))
        self.assertTrue(AuditLog.objects.filter(action="export", detail__contains="trajetória").exists())
        self.login("sec")
        self.assertEqual(self.client.get(reverse("longitudinal:export")).status_code, 403)


class RestrictedCoordinationTests(Base):
    coordenacao_restrita = True

    def test_coordination_outside_designation_is_refused(self):
        CoordinatorAssignment.objects.create(school=self.school, coordinator=self.coord,
                                             starts_on=timezone.localdate()).class_groups.add(self.turma_b)
        self.login("coord")
        self.assertEqual(self.client.get(reverse("longitudinal:student", args=[self.ana.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("longitudinal:student", args=[self.bea.pk])).status_code, 200)
        page = self.client.get(reverse("longitudinal:index")).content.decode()
        self.assertIn("designação", page)
        self.assertNotIn(">Ana<", page)
        self.assertEqual(self.client.post(reverse("longitudinal:model"), {"acao": "treinar"}).status_code, 403)


class EditingTests(Base):
    def test_secretary_records_a_prior_year_by_hand(self):
        url = reverse("longitudinal:prior_create", args=[self.ana.pk])
        self.login("prof")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login("sec")
        base = {"year": 2025, "grade_label": "1º ano", "school_name": "EC 10", "outcome": Outcome.APPROVED,
                "scale": "100"}
        self.client.post(url, {**base, "grades_text": "Matemática 70"})
        self.client.post(url, {**base, "grades_text": "Matemática: 170"})
        self.assertFalse(PriorYear.objects.exists())
        self.client.post(url, {**base, "grades_text": "Matemática: 70\nArte: B", "attendance_percent": "91,5"})
        p = PriorYear.objects.get()
        self.assertEqual((p.stage, p.created_by, p.attendance_percent), (1, self.sec, Decimal("91.5")))
        grades = {g.subject: g for g in p.grades.all()}
        self.assertEqual(grades["Matemática"].normalized(), 7.0)
        self.assertEqual(grades["Arte"].concept, "B")
        self.client.post(url, {**base, "grades_text": ""})  # mesmo ano e escola: recusado
        self.assertEqual(PriorYear.objects.count(), 1)
        self.client.post(reverse("longitudinal:prior_delete", args=[p.pk]))
        self.assertFalse(PriorYear.objects.exists())

    def test_import_checks_then_applies_and_reimport_updates(self):
        Student.objects.create(school=self.school, first_name="Bruno", last_name="Lima")
        Student.objects.create(school=self.school, first_name="Bruno", last_name="Lima")
        csv_text = ("codigo;estudante;ano;serie;escola;resultado;frequencia;Matemática;Português\n"
                    "A1;;2025;1º ano;EC 10;Reprovado;88,5;5,5;4\n"
                    "ZZ;;2025;1º ano;EC 10;Aprovado;;7;7\n"
                    ";Bruno Lima;2025;2º ano;EC 10;Aprovado;;7;7\n"
                    "A1;;2024;1º ano;EC 10;talvez;;7;7\n")
        self.login("sec")
        page = self.client.post(reverse("longitudinal:import"), {
            "arquivo": SimpleUploadedFile("h.csv", csv_text.encode("utf-8"))})
        self.assertContains(page, "1 linha pronta")
        self.assertContains(page, "não encontrado")
        self.assertContains(page, "informe o código")
        self.assertContains(page, "não reconhecido")
        self.assertFalse(PriorYear.objects.exists())  # conferir não grava
        token = page.context["token"]
        self.client.post(reverse("longitudinal:import"), {"dados": token + "x"})
        self.assertFalse(PriorYear.objects.exists())
        self.client.post(reverse("longitudinal:import"), {"dados": token})
        p = PriorYear.objects.get()
        self.assertEqual((p.outcome, p.attendance_percent, p.source), (Outcome.RETAINED, Decimal("88.5"), "importacao"))
        self.assertEqual(p.grades.count(), 2)
        self.client.post(reverse("longitudinal:import"), {"dados": token})
        self.assertEqual(PriorYear.objects.count(), 1)
        self.assertEqual(self.client.get(reverse("longitudinal:import_template")).status_code, 200)

    def test_year_results_by_class(self):
        e = Enrollment.objects.get(student=self.ana)
        url = reverse("longitudinal:results_class", args=[self.turma.pk])
        for user in ("prof", "coord", "resp"):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, 403, user)
        self.login("sec")
        self.assertContains(self.client.get(reverse("longitudinal:results")), "1º Ano A")
        self.client.post(url, {f"r-{e.pk}": Outcome.RETAINED, f"n-{e.pk}": "Ata do conselho"})
        r = YearResult.objects.get()
        self.assertEqual((r.outcome, r.decided_by, r.note), (Outcome.RETAINED, self.sec, "Ata do conselho"))
        self.client.post(url, {f"r-{e.pk}": ""})
        self.assertFalse(YearResult.objects.exists())
        other = ClassGroup.objects.create(school=self.school_b, school_year=SchoolYear.objects.create(
            school=self.school_b, name="2026"), name="X")
        self.assertEqual(self.client.get(reverse("longitudinal:results_class", args=[other.pk])).status_code, 404)


class StatsTests(TestCase):
    def test_known_values(self):
        p, lo, hi = stats.wilson(5, 10)
        self.assertAlmostEqual(lo, 0.2366, places=4)
        self.assertAlmostEqual(hi, 0.7634, places=4)
        rr = stats.risk_ratio(30, 100, 10, 100)
        self.assertAlmostEqual(rr["rr"], 3.0)
        self.assertAlmostEqual(rr["low"], 1.5508, places=3)
        self.assertAlmostEqual(rr["high"], 5.8033, places=3)
        self.assertAlmostEqual(stats.spearman([1, 2, 3, 4], [10, 20, 30, 45]), 1.0)
        self.assertEqual(stats.auc([1, 1, 0, 0], [0.9, 0.8, 0.2, 0.1]), 1.0)

    def test_logistic_recovers_known_coefficients(self):
        import random

        r = random.Random(3)
        X = [[r.gauss(0, 1), r.gauss(0, 1)] for _ in range(3000)]
        y = [int(r.random() < stats.sigmoid(0.5 + 1.5 * a - 1.0 * b)) for a, b in X]
        coefs, intercept = stats.fit_logistic(X, y, l2=0)
        self.assertAlmostEqual(coefs[0], 1.5, delta=0.15)
        self.assertAlmostEqual(coefs[1], -1.0, delta=0.15)
        self.assertAlmostEqual(intercept, 0.5, delta=0.15)
        p = stats.predict(coefs, intercept, X)
        cal_int, cal_slope = stats.calibration(y, p)
        self.assertAlmostEqual(cal_slope, 1.0, delta=0.05)  # calibrado nos próprios dados
        self.assertAlmostEqual(cal_int, 0.0, delta=0.05)


class ForecastTests(Base):
    def test_signal_is_approvable_and_noise_is_not(self):
        good = forecast.validate(forecast.synthetic_timelines())
        self.assertEqual(good["status"], ModelRun.Status.EXPERIMENTAL)
        self.assertTrue(good["approvable"], good["reasons"])
        self.assertGreater(good["metrics"]["auc"], good["baseline"]["auc"])
        noise = forecast.validate(forecast.synthetic_timelines(noise=True))
        self.assertFalse(noise["approvable"])
        self.assertTrue(any("AUC" in r for r in noise["reasons"]))
        few = forecast.validate(forecast.synthetic_timelines(n_students=40))
        self.assertEqual(few["status"], ModelRun.Status.INSUFFICIENT)

    def _approvable_run(self):
        res = forecast.validate(forecast.synthetic_timelines())
        metrics = {**res["metrics"], "approvable": True, "reasons": [], "test_year": res["test_year"]}
        return ModelRun.objects.create(school=self.school, name=forecast.NAME, version=forecast.VERSION,
                                       status=ModelRun.Status.EXPERIMENTAL, metrics=forecast._jsonable(metrics),
                                       coefficients=forecast._jsonable(res["model"]), n_test=res["n_test"])

    def test_training_approval_and_use(self):
        self.ana_history()
        self.login("sec")
        self.assertEqual(self.client.get(reverse("longitudinal:model")).status_code, 403)
        self.login("coord")
        self.client.post(reverse("longitudinal:model"), {"acao": "treinar"})
        real = forecast.runs(self.school).get()
        self.assertEqual(real.status, ModelRun.Status.INSUFFICIENT)  # dois estudantes não validam nada
        self.assertContains(self.client.get(reverse("longitudinal:model")), "Dados insuficientes")
        self.login("dir")
        self.client.post(reverse("longitudinal:model"), {"acao": "aprovar", "execucao": real.pk})
        real.refresh_from_db()
        self.assertEqual(real.status, ModelRun.Status.INSUFFICIENT)
        run = self._approvable_run()
        self.login("coord")
        self.assertEqual(self.client.post(reverse("longitudinal:model"),
                                          {"acao": "aprovar", "execucao": run.pk}).status_code, 403)
        url = reverse("longitudinal:student", args=[self.ana.pk])
        self.assertNotContains(self.client.get(url), "Chance de terminar")
        self.login("dir")
        self.client.post(reverse("longitudinal:model"), {"acao": "aprovar", "execucao": run.pk})
        run.refresh_from_db()
        self.assertEqual((run.status, run.decided_by), (ModelRun.Status.APPROVED, self.direc))
        self.assertContains(self.client.get(reverse("longitudinal:model")), "Modelo em uso")
        page = self.client.get(url)
        self.assertContains(page, "Chance de terminar 2026")
        self.assertContains(page, "O que mais pesou")
        self.login("resp")
        self.assertNotContains(self.client.get(url), "Chance de terminar")
        self.login("dir")
        self.client.post(reverse("longitudinal:model"), {"acao": "desativar", "execucao": run.pk})
        self.assertIsNone(forecast.active_run(self.school))


class CohortTests(Base):
    def test_school_analyses_hide_small_groups_and_validate_signals(self):
        kids = [Student.objects.create(school=self.school, first_name=f"E{i}", birth_date=dt.date(2016, 6, 1))
                for i in range(24)]
        for i, k in enumerate(kids):
            low = i < 12
            self.prior(k, 2024, "2º ano", Outcome.APPROVED, school="Escola A", Matematica=5 if low else 8)
            self.prior(k, 2025, "3º ano", Outcome.RETAINED if i < 6 else Outcome.APPROVED, school="Escola A",
                       Matematica=5 if low else 8.5)
        timelines = tl.build_many(self.school, kids)
        flow = {f["year"]: f for f in cohort.flow_rates(timelines)}
        self.assertAlmostEqual(flow[2025]["retido"], 25.0)
        self.assertEqual(flow[2025]["official"], 24)
        trans = cohort.transitions(timelines)
        self.assertEqual(trans["persist"]["n"], 12)
        self.assertAlmostEqual(trans["persist"]["pct"], 100.0)
        sig = {s["key"]: s for s in cohort.signal_validation(timelines)["rows"]}
        self.assertFalse(sig["adverse"]["hidden"])
        self.assertTrue(sig["adverse"]["clear"])
        self.assertTrue(sig["chronic"]["hidden"])  # ninguém com o sinal: não mostra
        self.assertGreater(cohort.stability(timelines)["rho"], 0.8)
        two = tl.build_many(self.school, kids[:3])
        self.assertTrue(cohort.flow_rates(two)[0]["hidden"])


class NoSensitiveDataTests(TestCase):
    def test_features_use_no_sensitive_data(self):
        names = {k for k, _ in forecast.FEATURES}
        self.assertEqual(names, {"average", "n_below", "attendance", "retentions", "distortion", "delta"})


class MenuTests(Base):
    def test_menu_entry_for_staff(self):
        from apps.core.navigation import LAYOUT

        for role in (Role.SECRETARIA, Role.COORDENACAO, Role.DIRECAO, Role.ADMIN):
            items = [i for _, group in LAYOUT[role.value] for i in group]
            self.assertIn("trajectory", items, role)
        self.assertNotIn("trajectory", [i for _, g in LAYOUT[Role.PROFESSOR.value] for i in g])
        self.assertTrue(User.objects.filter(role=Role.PROFESSOR).exists())


class ReliableChangeDiagnosisTests(TestCase):
    """O sinal 'ano atual diferente do próprio histórico' agora usa o Índice de Mudança
    Confiável (Jacobson & Truax, 1991), não um limiar fixo de 1 ponto."""

    def row(self, year, average, in_progress=False):
        return {"year": year, "in_progress": in_progress,
                "retained": False, "basis": "cursando" if in_progress else "oficial",
                "chronic": False, "attendance": None, "attendance_records": 0,
                "subjects": [], "average": average, "delta": None, "percentile": None,
                "distortion": None, "school_changes": 0, "stage": 1,
                "age": 8, "stage_label": "1º ano", "expected_age": 8}

    def keys(self, rows):
        return {f.key for f in diagnosis.diagnose(rows)}

    def test_reliable_drop_against_stable_history_fires(self):
        # Histórico estável (8,0; 7,6; 8,4) e queda para 6,5: RCI ≈ -3,25 → confiável.
        rows = [self.row(2022, 8.0), self.row(2023, 7.6), self.row(2024, 8.4),
                self.row(2025, 6.5, in_progress=True)]
        self.assertIn("proprio", self.keys(rows))

    def test_drop_within_noisy_history_does_not_fire(self):
        # Mesmo tipo de queda, mas o estudante sempre oscilou muito (9; 5; 7): a queda cabe
        # na flutuação dele (RCI ≈ -0,43) → nenhum falso alarme, ao contrário do limiar fixo.
        rows = [self.row(2022, 9.0), self.row(2023, 5.0), self.row(2024, 7.0),
                self.row(2025, 6.0, in_progress=True)]
        ks = self.keys(rows)
        self.assertNotIn("proprio", ks)
        self.assertNotIn("proprio_acima", ks)

    def test_flat_history_falls_back_to_point_threshold(self):
        # DP = 0 (8,0; 8,0; 8,0): sem RCI calculável, volta ao limiar de 1 ponto; 6,5 dispara.
        rows = [self.row(2022, 8.0), self.row(2023, 8.0), self.row(2024, 8.0),
                self.row(2025, 6.5, in_progress=True)]
        self.assertIn("proprio", self.keys(rows))


class SurvivalCurveTests(TestCase):
    """Kaplan-Meier de retencao sobre timelines sinteticas (a funcao so le outcome/in_progress)."""

    def tl(self, *outcomes_list):
        return {i: rows for i, rows in enumerate(outcomes_list)}

    def yr(self, outcome=Outcome.APPROVED, in_progress=False):
        return {"outcome": outcome, "in_progress": in_progress}

    def test_curve_treats_dropout_as_event_and_the_rest_as_censored(self):
        A = [self.yr(Outcome.DROPOUT)]                                           # abandono no 1 ano
        B = [self.yr(), self.yr(Outcome.DROPOUT)]                                # abandono no 2 ano
        C = [self.yr(), self.yr(), self.yr(Outcome.UNKNOWN, in_progress=True)]   # ainda na escola (censura)
        D = [self.yr(Outcome.TRANSFERRED)]                                       # transferido (censura)
        E = [self.yr(), self.yr(Outcome.UNKNOWN, in_progress=True)]              # censura no 2 ano
        F = [self.yr(), self.yr(), self.yr()]                                    # concluiu os anos observados
        km = cohort.survival_curve(self.tl(A, B, C, D, E, F))
        self.assertEqual((km["n"], km["events"]), (6, 2))
        surv = {s["t"]: round(s["survival"], 4) for s in km["steps"]}
        self.assertEqual(surv[1], round(5 / 6, 4))          # 1 abandono em 6 em risco
        self.assertEqual(surv[2], round(5 / 6 * 3 / 4, 4))  # +1 abandono em 4 em risco (censurados sairam)
        self.assertIsNone(km["median"])                     # retencao nunca cai abaixo de 50%

    def test_small_group_is_hidden(self):
        rows = [self.yr(Outcome.DROPOUT)]
        self.assertIsNone(cohort.survival_curve(self.tl(rows, rows, rows, rows)))  # menos de 5
