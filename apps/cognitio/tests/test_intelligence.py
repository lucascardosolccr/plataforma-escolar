"""Grafo, alertas precoces, modelo preditivo e intervenções (Prompt 16, etapas 5 a 7)."""

import inspect
from datetime import timedelta

from django.urls import reverse

from apps.cognitio import alerts as alerts_mod
from apps.cognitio import predictive
from apps.cognitio.alerts import generate_for_class
from apps.cognitio.evidence import rebuild_class
from apps.cognitio.graph import association, dependents, prerequisites
from apps.cognitio.models import (InterventionStrategy, LearningAlert, LearningIntervention, ModelRun, SkillEvidence,
                                  SkillObservation, SkillRelation)
from apps.cognitio.recommend import outcomes, recommend
from apps.cognitio.tests.test_evidence import Base
from apps.core.models import AuditLog
from apps.curriculum.models import CurriculumItem
from apps.pedagogy.models import Activity, AttendanceRecord, Submission


class GraphTests(Base):
    def test_progressions_are_proposed_with_rationale(self):
        rel = SkillRelation.objects.get(source__code="EF05MA02", target__code="EF06MA01")
        self.assertEqual((rel.kind, rel.status, rel.school), ("progressao", "proposta", None))
        self.assertIn("Números", rel.rationale)
        self.assertGreaterEqual(SkillRelation.objects.count(), 300)
        self.assertIn(rel, list(prerequisites(self.h1, self.school)))

    def test_curation_is_local_and_audited(self):
        rel = SkillRelation.objects.get(source__code="EF05MA02", target__code="EF06MA01")
        url = reverse("cognitio:relation_curate", args=[self.h1.pk])
        self.login(self.prof)
        self.assertEqual(self.client.post(url, {"id": rel.pk, "decisao": "rejeitar"}).status_code, 403)
        self.login(self.coord)
        self.client.post(url, {"id": rel.pk, "decisao": "rejeitar"})
        local = SkillRelation.objects.get(school=self.school, source__code="EF05MA02", target=self.h1)
        self.assertEqual(local.status, "rejeitada")
        rel.refresh_from_db()
        self.assertEqual(rel.status, "proposta")  # a proposta nacional não muda para outras escolas
        self.client.post(url, {"acao": "nova", "prerequisito": self.h2.pk, "tipo": "estatistica",
                               "confianca": "alta", "justificativa": "Registrada em reunião de área."})
        manual = SkillRelation.objects.get(school=self.school, source=self.h2, target=self.h1)
        self.assertEqual((manual.kind, manual.status, manual.origin), ("hipotese", "validada", "manual"))
        self.assertTrue(AuditLog.objects.filter(user=self.coord, detail__contains="relação").exists())
        r = self.client.get(reverse("cognitio:skill_graph", args=[self.h1.pk]) + f"?turma={self.cg.pk}")
        self.assertContains(r, "dados insuficientes")
        self.assertNotIn("EF05MA02", [x.source.code for x in r.context["prereqs"]])

    def test_association_requires_enough_students(self):
        res = association(self.h2, self.h1, self.school)
        self.assertEqual(res["enough"], False)


def obs(test, student, item, level, days_ago, subject=None):
    return SkillObservation.objects.create(school=test.school, student=student, item=item, class_group=test.cg,
                                           subject=subject or test.mat, teacher=test.prof, level=level,
                                           context="Sala", observed_on=test.today - timedelta(days=days_ago))


class AlertTests(Base):
    def test_rules_generate_explained_alerts_and_resolve(self):
        for d in (40, 20, 2):
            obs(self, self.ana, self.h1, 1, d)
        obs(self, self.bia, self.h1, 1, 10)
        obs(self, self.bia, self.h1, 2, 5)
        obs(self, self.caio, self.h1, 1, 30)
        obs(self, self.caio, self.h1, 5, 3)
        # Prerequisito: EF05MA02 → EF06MA01. Bia com dificuldade em EF05MA02 e EF06MA01 numa atividade próxima.
        pre = CurriculumItem.objects.get(code="EF05MA02")
        obs(self, self.bia, pre, 1, 9)
        obs(self, self.bia, pre, 1, 8)
        act = Activity.objects.create(school=self.school, class_group=self.cg, subject=self.mat, title="Reta",
                                      class_date=self.today + timedelta(days=5), created_by=self.prof)
        act.curriculum.add(self.h1)
        rebuild_class(self.cg)
        new, active = generate_for_class(self.cg, self.today)
        rules = set(LearningAlert.objects.values_list("rule", flat=True))
        self.assertTrue({"dificuldade_persistente", "contraditoria", "prerequisito", "retomada_coletiva"} <= rules)
        a = LearningAlert.objects.get(rule="dificuldade_persistente")
        self.assertEqual(a.student, self.ana)
        self.assertIn("exploratória", a.method)
        self.assertTrue(a.limitations and a.next_action and a.evidence_ids)
        self.assertEqual(LearningAlert.objects.get(rule="prerequisito").student, self.bia)
        # Recalcular não duplica.
        generate_for_class(self.cg, self.today)
        self.assertEqual(LearningAlert.objects.count(), active)
        # A condição some → alerta resolvido automaticamente.
        for d in (1, 1, 0, 0):
            obs(self, self.ana, self.h1, 5, d)
        rebuild_class(self.cg)
        generate_for_class(self.cg, self.today)
        a.refresh_from_db()
        self.assertEqual((a.active, a.status), (False, "resolvido"))

    def test_general_signals_use_attendance_and_deliveries_only(self):
        for d in range(1, 9):
            AttendanceRecord.objects.create(school=self.school, class_group=self.cg, student=self.caio,
                                            date=self.today - timedelta(days=d), status="falta" if d % 2 else "presente")
        for i in range(3):
            act = Activity.objects.create(school=self.school, class_group=self.cg, subject=self.mat, title=f"A{i}",
                                          class_date=self.today - timedelta(days=10), deadline=self.today - timedelta(days=9),
                                          created_by=self.prof, status="publicada")
            Submission.objects.create(school=self.school, activity=act, student=self.caio, status="nao_entregue")
        generate_for_class(self.cg, self.today)
        al = LearningAlert.objects.get(rule="acompanhamento", student=self.caio)
        self.assertEqual(len(al.factors), 2)
        source = inspect.getsource(alerts_mod)
        self.assertNotIn("inclusion", source)  # nunca usa laudo, diagnóstico ou necessidade específica

    def test_review_permissions_and_discard_needs_reason(self):
        for d in (40, 20, 2):
            obs(self, self.ana, self.h1, 1, d)
        rebuild_class(self.cg)
        generate_for_class(self.cg, self.today)
        alert = LearningAlert.objects.get(rule="dificuldade_persistente")
        url = reverse("cognitio:alert_review", args=[alert.pk])
        self.login(self.prof_b)
        self.assertEqual(self.client.post(url, {"decisao": "analisar"}).status_code, 404)
        self.login(self.prof_geo)
        self.assertEqual(self.client.get(reverse("cognitio:alerts")).context["page"].paginator.count, 0)
        self.login(self.prof)
        self.client.post(url, {"decisao": "descartar"})
        alert.refresh_from_db()
        self.assertEqual(alert.status, "novo")
        self.client.post(url, {"decisao": "descartar", "registro": "Já retomado em sala."})
        alert.refresh_from_db()
        self.assertEqual((alert.status, alert.reviewed_by), ("descartado", self.prof))
        r = self.client.get(reverse("cognitio:alerts") + "?situacao=descartado")
        self.assertContains(r, "Já retomado em sala.")


class PredictiveTests(Base):
    def test_insufficient_data_stays_exploratory(self):
        self.login(self.dir)
        self.client.post(reverse("cognitio:models"), {"acao": "treinar"})
        run = ModelRun.objects.get()
        self.assertEqual(run.status, "insuficiente")
        self.assertIn("pelo menos", run.notes)
        self.client.post(reverse("cognitio:models"), {"acao": "aprovar", "id": run.pk})
        run.refresh_from_db()
        self.assertEqual(run.status, "insuficiente")  # não se aprova o que não foi validado
        self.assertIsNone(predictive.active_run(self.school))
        self.login(self.prof)
        self.assertEqual(self.client.get(reverse("cognitio:models")).status_code, 403)

    def test_algorithm_and_metrics_are_technically_correct(self):
        m = predictive.metrics([1, 1, 0, 0], [0.9, 0.4, 0.2, 0.6])
        self.assertEqual((m["tp"], m["fn"], m["tn"], m["fp"]), (1, 1, 1, 1))
        self.assertAlmostEqual(m["auc"], 0.75)
        synthetic = predictive.synthetic_check()  # dado sintético: só prova o código, não a eficácia
        self.assertGreater(synthetic["auc"], 0.7)


class InterventionTests(Base):
    def setUp(self):
        super().setUp()
        for d in (30, 20):
            obs(self, self.ana, self.h1, 1, d)
            obs(self, self.bia, self.h1, 2, d)
        rebuild_class(self.cg)

    def test_recommendation_is_specific_and_explained(self):
        recs = recommend(self.h1, self.school, error_types=["conceitual"])
        self.assertTrue(recs)
        top = recs[0]
        self.assertEqual(top["strategy"].component, "Matemática")
        self.assertTrue(top["reasons"])
        geo = CurriculumItem.objects.get(code="EF06GE01")
        self.assertTrue(all(r["strategy"].component in ("Geografia", "") for r in recommend(geo, self.school)))
        self.assertTrue(InterventionStrategy.objects.filter(evidence_level="pesquisa").exclude(references="").exists())

    def test_intervention_from_class_and_outcome(self):
        self.login(self.prof)
        url = reverse("cognitio:intervention_create") + \
            f"?turma={self.cg.pk}&disciplina={self.mat.pk}&habilidade={self.h1.pk}&estudante={self.ana.pk}"
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        form = r.context["form"]
        start = self.today - timedelta(days=10)
        data = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in form.initial.items() if v is not None}
        data.update(students=[self.ana.pk, self.bia.pk], starts_on=start.isoformat(),
                    review_on=(start + timedelta(days=14)).isoformat(), complexity=2, minutes=30)
        r = self.client.post(url, data)
        self.assertEqual(r.status_code, 302)
        iv = LearningIntervention.objects.get()
        obs(self, self.ana, self.h1, 5, 3)
        rebuild_class(self.cg)
        res = {r["student"].first_name: r["result"] for r in outcomes(iv)}
        self.assertEqual(res, {"Ana": "melhorou", "Bia": "sem_evidencia"})
        # Prompt 18 §12/§20.16: sem melhora, o sistema pede para rever a hipótese antes de repetir.
        from apps.cognitio.recommend import NEXT_AFTER
        obs(self, self.bia, self.h1, 1, 12)
        obs(self, self.bia, self.h1, 1, 2)
        rebuild_class(self.cg)
        bia = [r for r in outcomes(iv) if r["student"] == self.bia][0]
        self.assertIn(bia["result"], ("estavel", "piorou"))  # sem melhora
        self.assertEqual(bia["next"], NEXT_AFTER[bia["result"]])
        self.assertContains(self.client.get(reverse("cognitio:intervention_detail", args=[iv.pk])),
                            "reveja a hipótese")
        self.assertContains(self.client.get(reverse("cognitio:intervention_detail", args=[iv.pk])),
                            "não prova que a intervenção causou")
        self.login(self.prof_b)
        self.assertEqual(self.client.get(reverse("cognitio:intervention_detail", args=[iv.pk])).status_code, 404)

    def test_trail_starts_with_weak_prerequisites(self):
        pre = CurriculumItem.objects.get(code="EF05MA02")
        obs(self, self.ana, pre, 1, 25)
        obs(self, self.ana, pre, 1, 24)
        rebuild_class(self.cg)
        self.login(self.prof)
        url = reverse("cognitio:trail_create", args=[self.cg.pk, self.mat.pk, self.h1.pk]) + f"?estudante={self.ana.pk}"
        r = self.client.get(url)
        kinds = [s["kind"] for s in r.context["steps"]]
        self.assertEqual(kinds[0], "Retomar pré-requisito")
        self.assertEqual(kinds[-1], "Verificar novamente")
        r = self.client.post(url, {"estudante": [self.ana.pk], "passo": [str(i) for i in range(len(kinds))]})
        self.assertEqual(LearningIntervention.objects.filter(trail__isnull=False).count(), len(kinds))
        self.assertEqual(LearningIntervention.objects.order_by("order").first().item.code, "EF05MA02")

    def test_school_strategy_is_experimental(self):
        self.login(self.prof)
        self.client.post(reverse("cognitio:strategies"), {"title": "Jogo de frações", "component": "Matemática",
                                                          "objective": "Comparar frações", "procedures": "Jogo em duplas",
                                                          "minutes": 20})
        s = InterventionStrategy.objects.get(title="Jogo de frações")
        self.assertEqual((s.evidence_level, s.school), ("experimental", self.school))
