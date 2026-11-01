"""Prompt 17: lacunas, decisão do professor, propagação, priorização, plano de recuperação, BKT,
assistente, reavaliação programada e pré-requisitos da turma."""

from datetime import timedelta

from django.urls import reverse

from apps.cognitio import assistant, bkt, gaps
from apps.cognitio.evidence import rebuild_class
from apps.cognitio.models import (LearningIntervention, MasteryScale, ModelRun, SkillJudgment, SkillObservation,
                                  SkillRelation, SkillRelationChange)
from apps.cognitio.recommend import next_step
from apps.cognitio.tests.test_evidence import Base
from apps.core.models import AuditLog
from apps.curriculum.models import CurriculumItem


class P17Base(Base):
    def setUp(self):
        super().setUp()
        self.h3 = CurriculumItem.objects.get(code="EF07MA01")
        # grafo local validado: h1 → h2 → h3
        self.r12 = SkillRelation.objects.create(school=self.school, source=self.h1, target=self.h2, kind="prerequisito",
                                                confidence="alta", status="validada", origin="manual",
                                                rationale="Comparar e ordenar sustenta o cálculo.")
        self.r23 = SkillRelation.objects.create(school=self.school, source=self.h2, target=self.h3, kind="conceitual",
                                                confidence="media", status="proposta", origin="manual")

    def obs(self, student, item, level, days_ago, context="Sala", subject=None):
        return SkillObservation.objects.create(school=self.school, student=student, item=item, class_group=self.cg,
                                               subject=subject or self.mat, teacher=self.prof, level=level,
                                               context=context, observed_on=self.today - timedelta(days=days_ago))

    def state(self, student, item):
        return gaps.item_state(student, item, MasteryScale.for_school(self.school), self.today)


class GapTests(P17Base):
    def test_gap_kinds_with_rationale(self):
        scale = MasteryScale.for_school(self.school)
        # sem evidência: não é "não sabe"
        kind, why = gaps.classify(self.state(self.ana, self.h1), scale, self.today)
        self.assertEqual(kind, "sem_evidencia")
        self.assertIn("não quer dizer ausência de conhecimento", why)
        # dificuldade numa situação só
        self.obs(self.ana, self.h1, 1, 3)
        self.obs(self.ana, self.h1, 1, 2)
        rebuild_class(self.cg)
        self.assertEqual(gaps.classify(self.state(self.ana, self.h1), scale, self.today)[0], "situacao")
        # outra situação, outra data: confirmada por múltiplas evidências
        self.obs(self.bia, self.h1, 1, 5, context="Quadro")
        self.obs(self.bia, self.h1, 1, 1, context="Prova oral")
        rebuild_class(self.cg)
        self.assertEqual(gaps.classify(self.state(self.bia, self.h1), scale, self.today)[0], "confirmada")
        # evidência antiga: reavaliar
        self.obs(self.caio, self.h2, 1, 200, context="A")
        self.obs(self.caio, self.h2, 1, 190, context="B")
        rebuild_class(self.cg)
        self.assertEqual(gaps.classify(self.state(self.caio, self.h2), scale, self.today)[0], "reavaliar")

    def test_analysis_is_hypothesis_not_verdict_and_judgment_prevails_until_new_evidence(self):
        self.obs(self.ana, self.h1, 1, 4, "A")
        self.obs(self.ana, self.h1, 1, 2, "B")
        rebuild_class(self.cg)
        g = gaps.gap_analysis(self.ana, self.h2, self.school, today=self.today)
        row = next(r for r in g["rows"] if r["item"] == self.h1)
        self.assertEqual(row["kind"], "confirmada")
        self.assertIn(f"Para desenvolver {self.h2.code}, o estudante apresenta evidências suficientes em", g["summary"])
        self.assertIn("Recomenda-se verificar", g["summary"])
        self.assertNotIn("não conseguirá", g["summary"])
        # decisão do professor com fundamento vale até surgir evidência nova
        SkillJudgment.objects.create(school=self.school, student=self.ana, item=self.h1, state="consolidada",
                                     rationale="Resolveu três problemas na aula de hoje sem apoio.",
                                     decided_by=self.prof, decided_on=self.today)
        st = self.state(self.ana, self.h1)
        self.assertEqual((st.effective, st.newer_evidence), ("consolidada", False))
        self.assertIsNone(gaps.classify(st, MasteryScale.for_school(self.school), self.today)[0])
        self.obs(self.ana, self.h1, 2, -1)  # evidência posterior à decisão (amanhã, para o teste)
        rebuild_class(self.cg)
        st = gaps.item_state(self.ana, self.h1, today=self.today + timedelta(days=1))
        self.assertTrue(st.newer_evidence)
        self.assertNotEqual(st.effective, "consolidada")

    def test_propagation_without_multiplying_and_confidence_rules(self):
        self.obs(self.ana, self.h1, 1, 3, "A")
        self.obs(self.ana, self.h1, 1, 1, "B")
        rebuild_class(self.cg)
        rows = {r["item"]: r for r in gaps.propagation(self.ana, self.h1, self.school, today=self.today)}
        self.assertEqual(rows[self.h2]["distance"], 1)
        self.assertEqual(rows[self.h2]["confidence"], "alta")  # relação validada e direta
        self.assertEqual(rows[self.h3]["distance"], 2)
        self.assertEqual(rows[self.h3]["confidence"], "baixa")  # passa por relação não validada
        self.assertTrue(rows[self.h3]["needs_check"])
        for r in rows.values():
            self.assertNotIn("%", r["impact"])
        sc = gaps.scenarios(self.ana, self.h1, self.school, list(rows.values()))
        self.assertIn("não uma previsão de fracasso", sc["A"]["text"])
        self.assertIsNone(sc["B"]["data"])  # sem resultados suficientes, não estima

    def test_priorities_are_explained_and_reorderable(self):
        self.obs(self.ana, self.h1, 1, 40, "A")
        self.obs(self.ana, self.h1, 1, 2, "B")
        self.obs(self.ana, self.h2, 5, 3, "A")
        self.obs(self.ana, self.h2, 5, 1, "B")
        rebuild_class(self.cg)
        rows = gaps.priorities(self.ana, self.school, today=self.today)
        self.assertEqual([r["item"] for r in rows], [self.h1])  # consolidada não entra
        labels = [label for label, _ in rows[0]["parts"]]
        self.assertTrue(any("dependente" in label for label in labels))
        self.assertTrue(any("persistência" in label for label in labels))
        self.assertEqual(rows[0]["score"], sum(p for _, p in rows[0]["parts"]))
        self.assertEqual(len(gaps.priorities(self.ana, self.school, order="recencia", today=self.today)), 1)


class ScreenTests(P17Base):
    def test_projection_page_access_and_audit(self):
        url = reverse("cognitio:student_projection", args=[self.ana.pk]) + f"?habilidade={self.h2.pk}"
        self.login(self.prof)
        r = self.client.get(url)
        self.assertContains(r, "Mapa de Aprendizagem e Projeção de Competências")
        self.assertContains(r, "Nível 3 indisponível")
        self.assertTrue(AuditLog.objects.filter(detail__startswith="Consultou o mapa de aprendizagem").exists())
        for user in (self.prof_b, self.fam, self.sec):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, 403, user.username)

    def test_teacher_judgment_requires_rationale_and_teaching(self):
        url = reverse("cognitio:judgment_save", args=[self.ana.pk])
        self.login(self.prof)
        self.client.post(url, {"habilidade": self.h1.pk, "estado": "consolidada", "fundamento": "curto"})
        self.assertFalse(SkillJudgment.objects.exists())
        self.client.post(url, {"habilidade": self.h1.pk, "estado": "consolidada",
                               "fundamento": "Explicou o raciocínio com exemplos próprios."})
        self.assertTrue(SkillJudgment.objects.filter(active=True, decided_by=self.prof).exists())
        self.client.post(url, {"habilidade": self.h1.pk, "acao": "retirar"})
        self.assertFalse(SkillJudgment.objects.filter(active=True).exists())
        self.login(self.prof_geo)  # leciona Geografia: não decide sobre Matemática
        r = self.client.post(url, {"habilidade": self.h1.pk, "estado": "consolidada",
                                   "fundamento": "Tentativa fora da própria disciplina."})
        self.assertEqual(r.status_code, 403)

    def test_structure_page_and_typed_relation_with_history(self):
        self.login(self.coord)
        r = self.client.get(reverse("cognitio:skill_graph", args=[self.h2.pk]))
        for section in ("A. Objetivo de chegada", "B. Conhecimentos anteriores", "C. Evidências esperadas",
                        "D. Critérios de domínio", "E. Dependências posteriores", "F. Consequências possíveis",
                        "G. Intervenções possíveis", "H. Verificação posterior"):
            self.assertContains(r, section)
        lp = CurriculumItem.objects.get(code="EF05LP09")
        self.client.post(reverse("cognitio:relation_curate", args=[self.h2.pk]),
                         {"acao": "nova", "codigo": lp.code, "tipo": "transversal", "confianca": "baixa",
                          "fonte": "Hipótese da equipe", "justificativa": "Leitura do enunciado"})
        rel = SkillRelation.objects.get(source=lp, target=self.h2)
        self.assertEqual((rel.kind, rel.reference), ("transversal", "Hipótese da equipe"))
        self.assertEqual(SkillRelationChange.objects.get(relation=rel).action, "criou")

    def test_recovery_plan_from_gap_and_next_step(self):
        self.obs(self.ana, self.h1, 1, 4, "A")
        self.obs(self.ana, self.h1, 1, 2, "B")
        rebuild_class(self.cg)
        self.login(self.prof)
        url = (reverse("cognitio:intervention_create") + f"?turma={self.cg.pk}&disciplina={self.mat.pk}"
               f"&habilidade={self.h1.pk}&estudante={self.ana.pk}&alvo={self.h2.pk}")
        r = self.client.get(url)
        form = r.context["form"]
        self.assertIn(self.h1.code, form.initial["prereqs_to_check"])
        self.assertIn("Recomenda-se verificar", form.initial["evidence_basis"])
        data = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in form.initial.items() if v is not None}
        data.update(students=[self.ana.pk], complexity=2, minutes=30,
                    starts_on=(self.today - timedelta(days=1)).isoformat(),
                    review_on=(self.today + timedelta(days=14)).isoformat())
        self.client.post(url, data)
        iv = LearningIntervention.objects.get()
        self.assertEqual((iv.item, iv.target_item), (self.h1, self.h2))
        self.assertEqual(next_step(iv)["decision"], "verificar")  # sem evidência posterior, não conclui
        self.obs(self.ana, self.h1, 5, 0, "C")
        self.obs(self.ana, self.h1, 5, 0, "D")
        rebuild_class(self.cg)
        self.assertIn(next_step(iv)["decision"], ("continuar", "encerrar"))


class BKTTests(P17Base):
    def test_synthetic_recovery_and_no_estimate_without_approval(self):
        res = bkt.synthetic_check()
        for k in ("l0", "t", "g", "s"):
            self.assertLessEqual(abs(res["fitted"][k] - res["true"][k]), 0.11, k)
        run = bkt.train_and_validate(self.school)
        self.assertEqual(run.status, ModelRun.Status.INSUFFICIENT)  # base de teste pequena
        self.assertIsNone(bkt.estimate(bkt.active_run(self.school), self.ana, self.h1))


class AssistantTests(P17Base):
    def test_examples_are_understood(self):
        expected = ["prerequisitos", "evidencias_lacuna", "dependentes", "intervencao_semelhante", "retomar",
                    "depois_recuperacao", "sem_evidencia", "atividades", "evidencias_coletar", "nao_avaliadas"]
        self.assertEqual([assistant.detect(q)[0] for q in assistant.EXAMPLES], expected)
        self.assertIsNone(assistant.detect("bom dia"))

    def test_answers_use_data_and_declare_missing(self):
        a = assistant.answer(self.prof, "Quais pré-requisitos o aluno precisa desenvolver?", student=self.ana)
        self.assertIn("código da habilidade", a.missing)
        a = assistant.answer(self.prof, f"Quais pré-requisitos o aluno precisa desenvolver para {self.h2.code}?",
                             student=self.ana)
        self.assertTrue(any(self.h1.code in text for text, _ in a.items))
        self.assertTrue(a.limits)
        # estudante fora do alcance não é reconhecido pelo nome
        self.assertNotIn(self.ana, assistant.visible_students(self.prof_b))
        self.login(self.prof)
        r = self.client.get(reverse("cognitio:assistant"), {"pergunta": f"O que pode depender de {self.h1.code}?"})
        self.assertContains(r, self.h2.code)
        self.assertTrue(AuditLog.objects.filter(detail__startswith="Assistente EIA-Cognitio").exists())


class RecheckAndClassTests(P17Base):
    def test_scheduled_recheck_shows_in_pending_until_new_evidence(self):
        url = reverse("cognitio:observation_create", args=[self.cg.pk, self.mat.pk])
        self.login(self.prof)
        self.client.post(url, {"item": self.h1.pk, "level": 2, "context": "Quadro",
                               "observed_on": (self.today - timedelta(days=10)).isoformat(),
                               "recheck_on": (self.today - timedelta(days=1)).isoformat(),
                               "students": [self.ana.pk], "evaluation": self.ev.pk})
        o = SkillObservation.objects.get()
        self.assertEqual((o.evaluation, o.recheck_on), (self.ev, self.today - timedelta(days=1)))
        self.assertContains(self.client.get(reverse("pending_center")), "Reavaliações de habilidade programadas")

    def test_class_prerequisites_for_upcoming_content(self):
        self.ev.date = self.today + timedelta(days=5)
        self.ev.save()
        self.ev.curriculum.add(self.h2)
        self.obs(self.ana, self.h1, 1, 3, "A")
        self.obs(self.ana, self.h1, 1, 1, "B")
        self.obs(self.bia, self.h1, 5, 3, "A")
        self.obs(self.bia, self.h1, 5, 1, "B")
        rebuild_class(self.cg)
        needs = gaps.class_prerequisite_needs(self.cg, self.mat, self.school, [self.ana, self.bia, self.caio])
        row = next(r for r in needs["rows"] if r["item"] == self.h1)
        self.assertEqual(([s.pk for s in row["weak"]], [s.pk for s in row["ok"]], [s.pk for s in row["missing"]]),
                         ([self.ana.pk], [self.bia.pk], [self.caio.pk]))
        self.login(self.prof)
        r = self.client.get(reverse("cognitio:class_view", args=[self.cg.pk]), {"disciplina": self.mat.pk})
        self.assertContains(r, "Pré-requisitos das próximas habilidades")


class DashboardP17Tests(P17Base):
    def test_teacher_critical_prereqs_and_coordination_articulation(self):
        self.ev.date = self.today + timedelta(days=5)
        self.ev.save()
        self.ev.curriculum.add(self.h2)
        self.obs(self.ana, self.h1, 1, 3, "A")
        self.obs(self.ana, self.h1, 1, 1, "B")
        geo = CurriculumItem.objects.get(code="EF06GE01")
        for ctx in ("A", "B"):
            SkillObservation.objects.create(school=self.school, student=self.ana, item=geo, class_group=self.cg,
                                            subject=self.geo, teacher=self.prof_geo, level=1, context=ctx,
                                            observed_on=self.today - timedelta(days=2))
        rebuild_class(self.cg)
        self.login(self.prof)
        r = self.client.get(reverse("cognitio:dashboard"))
        self.assertEqual([c["item"] for c in r.context["critical"]], [self.h1])
        self.assertContains(r, "Pré-requisitos críticos para o conteúdo atual")
        self.login(self.coord)
        r = self.client.get(reverse("cognitio:dashboard"))
        self.assertEqual([(st, comps) for st, comps in r.context["cross_component"]],
                         [(self.ana, ["Geografia", "Matemática"])])


class ConsistencyAndIntegrationTests(P17Base):
    def test_teacher_decision_is_the_same_on_every_screen(self):
        from apps.cognitio.alerts import generate_for_class
        from apps.cognitio.models import LearningAlert
        from apps.cognitio.summary import student_components

        for d, ctx in ((40, "A"), (20, "B"), (2, "C")):
            self.obs(self.ana, self.h1, 1, d, ctx)
        rebuild_class(self.cg)
        SkillJudgment.objects.create(school=self.school, student=self.ana, item=self.h1, state="consolidada",
                                     rationale="Explicou e resolveu sozinha na aula de hoje.", decided_by=self.prof,
                                     decided_on=self.today)
        self.login(self.prof)
        r = self.client.get(reverse("cognitio:class_view", args=[self.cg.pk]), {"disciplina": self.mat.pk})
        cell = next(a for st, row in r.context["matrix"] if st == self.ana for it, a in row if it == self.h1)
        self.assertEqual((cell.state, cell.computed_state), ("consolidada", "dificuldade"))
        r = self.client.get(reverse("cognitio:student_map", args=[self.ana.pk]), {"habilidade": self.h1.pk})
        self.assertContains(r, "decisão do professor")
        comps = {c["component"]: dict((k, n) for k, _l, _c, n in c["counts"])
                 for c in student_components(self.prof, self.ana)}
        self.assertEqual(comps["Matemática"].get("consolidada"), 1)
        generate_for_class(self.cg, self.today)
        self.assertFalse(LearningAlert.objects.filter(student=self.ana, item=self.h1, active=True).exists())

    def test_lesson_plan_shows_prerequisites_of_its_skills(self):
        from apps.pedagogy.models import LessonPlan

        self.obs(self.ana, self.h1, 1, 3, "A")
        self.obs(self.ana, self.h1, 1, 1, "B")
        rebuild_class(self.cg)
        plan = LessonPlan.objects.create(school=self.school, teacher=self.prof, class_group=self.cg, subject=self.mat,
                                         starts_on=self.today, ends_on=self.today + timedelta(days=4), title="P",
                                         content="c", objectives="o")
        plan.curriculum.set([self.h2])
        self.login(self.prof)
        r = self.client.get(reverse("pedagogy:lessonplan_detail", args=[plan.pk]))
        self.assertContains(r, "Antes de começar: pré-requisitos das habilidades deste planejamento")
        row = next(x for x in r.context["prereq_needs"]["rows"] if x["item"] == self.h1)
        self.assertEqual([s.pk for s in row["weak"]], [self.ana.pk])

    def test_assistant_paraphrases_and_skill_field(self):
        probes = {
            "O que falta para o estudante chegar em EF01MA02?": "prerequisitos",
            "Qual o impacto se ele não aprender EF01MA01?": "dependentes",
            "Como trabalhar EF01MA02 com a turma?": "atividades",
            "Como saber se ele aprendeu EF01MA02?": "evidencias_coletar",
            "A intervenção funcionou?": "depois_recuperacao",
            "Quem ainda não foi avaliado em EF01MA02?": "sem_evidencia",
            "O que revisar antes da próxima unidade?": "retomar",
        }
        for q, intent in probes.items():
            self.assertEqual(assistant.detect(q)[0], intent, q)
        self.login(self.prof)
        r = self.client.get(reverse("cognitio:assistant"), {"pergunta": "O que pode depender desta habilidade?",
                                                            "habilidade": self.h1.code, "turma": self.cg.pk})
        self.assertContains(r, self.h2.code)
        self.assertContains(r, '<datalist id="ph-list">')


class CouncilTests(P17Base):
    def test_council_page_per_student_alphabetical_with_gaps_and_scope(self):
        for d, ctx in ((10, "A"), (3, "B")):
            self.obs(self.bia, self.h1, 1, d, ctx)
        self.obs(self.ana, self.h2, 5, 4, "A")
        self.obs(self.ana, self.h2, 5, 2, "B")
        geo = CurriculumItem.objects.get(code="EF06GE01")
        SkillObservation.objects.create(school=self.school, student=self.caio, item=geo, class_group=self.cg,
                                        subject=self.geo, teacher=self.prof_geo, level=1, context="A",
                                        observed_on=self.today - timedelta(days=2))
        iv = LearningIntervention.objects.create(school=self.school, class_group=self.cg, subject=self.mat,
                                                 item=self.h1, title="Retomada", objective="o", activity="a",
                                                 starts_on=self.today - timedelta(days=5), review_on=self.today,
                                                 created_by=self.prof)
        iv.students.set([self.bia])
        rebuild_class(self.cg)
        url = reverse("cognitio:class_council", args=[self.cg.pk])
        self.login(self.prof)
        r = self.client.get(url)
        rows = r.context["rows"]
        self.assertEqual([x["student"] for x in rows], sorted([self.ana, self.bia, self.caio], key=lambda s: s.full_name))
        by = {x["student"]: x for x in rows}
        self.assertEqual(by[self.bia]["confirmed"], [self.h1])
        self.assertTrue(by[self.caio]["no_evidence"])  # Geografia fica fora para o professor de Matemática
        self.assertContains(r, "Não há pontuação")
        self.assertContains(r, "Situação das intervenções pelas evidências posteriores")
        self.assertTrue(AuditLog.objects.filter(detail__startswith="Consultou a preparação do conselho").exists())
        self.login(self.coord)
        by = {x["student"]: x for x in self.client.get(url).context["rows"]}
        self.assertFalse(by[self.caio]["no_evidence"])
        for user in (self.prof_b, self.fam, self.sec):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, 403, user.username)


class NotEvaluatedAndPerformanceTests(P17Base):
    def test_worked_but_not_evaluated_listed_per_class_with_observation_link(self):
        from apps.pedagogy.models import LessonPlan

        self.login(self.prof)  # sem habilidade ligada a nada: diz o que falta, não "está tudo avaliado"
        self.assertContains(self.client.get(reverse("cognitio:dashboard")), "Ligue as habilidades ao planejar")
        self.assertIn("Ligue as habilidades",
                      assistant.answer(self.prof, "Quais habilidades ainda não foram avaliadas?").missing)
        plan = LessonPlan.objects.create(school=self.school, teacher=self.prof, class_group=self.cg, subject=self.mat,
                                         starts_on=self.today - timedelta(days=9),
                                         ends_on=self.today - timedelta(days=2), title="P", content="c",
                                         objectives="o")
        plan.curriculum.set([self.h1, self.h2])
        self.obs(self.ana, self.h1, 4, 1)  # h1 já tem registro na turma; h2 não
        rebuild_class(self.cg)
        self.login(self.prof)
        r = self.client.get(reverse("cognitio:dashboard"))
        rows = r.context["not_evaluated_rows"]["rows"]
        self.assertEqual([(x["item"], x["cg"], x["origin"]) for x in rows], [(self.h2, self.cg, "planejamento")])
        link = reverse("cognitio:observation_create", args=[self.cg.pk, self.mat.pk]) + f"?item={self.h2.pk}"
        self.assertContains(r, link)
        self.assertContains(r, "Não quer dizer que a turma não aprendeu")
        # a mesma resposta no assistente, só no alcance de quem pergunta
        q = "Quais habilidades já trabalhadas ainda não foram avaliadas?"
        self.assertEqual(assistant.detect(q)[0], "nao_avaliadas")
        self.assertEqual(assistant.detect("Quem ainda não foi avaliado em EF01MA02?")[0], "sem_evidencia")
        a = assistant.answer(self.prof, q, class_group=self.cg)
        self.assertEqual([url for _, url in a.items], [link])
        self.assertEqual(assistant.answer(self.prof_b, q).items, [])  # não leciona nesta turma

    def test_propagation_same_result_and_queries_do_not_grow_with_the_graph(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.obs(self.ana, self.h1, 1, 3, "A")
        self.obs(self.ana, self.h1, 1, 1, "B")
        self.obs(self.ana, self.h2, 5, 2, "A")
        rebuild_class(self.cg)
        SkillJudgment.objects.create(school=self.school, student=self.ana, item=self.h2, state="reverificar",
                                     rationale="Quero ver de novo.", decided_by=self.prof, decided_on=self.today)

        def run():
            with CaptureQueriesContext(connection) as q:
                rows = gaps.propagation(self.ana, self.h1, self.school, today=self.today)
            return rows, len(q.captured_queries)

        rows, before = run()
        for r in rows:  # o cálculo em lote dá o mesmo estado que habilidade por habilidade
            one = self.state(self.ana, r["item"])
            self.assertEqual((r["a"].effective, r["a"].state), (one.effective, one.state), r["item"].code)
        self.assertEqual(next(r for r in rows if r["item"] == self.h2)["a"].effective, "reverificar")
        reached = {self.h1.pk} | {r["item"].pk for r in rows}
        extra = list(CurriculumItem.objects.filter(component="Matemática", kind="habilidade")
                     .exclude(pk__in=reached)[:4])
        for it in extra:
            SkillRelation.objects.create(school=self.school, source=self.h3, target=it, kind="progressao",
                                         confidence="media", status="validada", origin="manual")
        n_before = len(rows)
        rows, after = run()
        self.assertEqual(len(rows), n_before + len(extra))
        self.assertLessEqual(after - before, 3 * len(extra))  # antes: cerca de 15 consultas por habilidade


class AccessibilityTests(P17Base):
    """Campos de formulário com rótulo e botões e links com nome nas telas novas (inclui a busca do layout)."""

    def audit(self, html):
        from html.parser import HTMLParser

        class P(HTMLParser):
            def __init__(self):
                super().__init__()
                self.fors, self.fields, self.depth, self.open, self.bad = set(), [], 0, None, []

            def handle_starttag(self, tag, attrs):
                a = dict(attrs)
                if tag == "label":
                    self.depth += 1
                    self.fors.add(a.get("for"))
                if tag in ("input", "select", "textarea") and a.get("type") not in ("hidden", "submit", "button"):
                    self.fields.append((a.get("id"), bool(a.get("aria-label")), self.depth > 0, a.get("name")))
                if tag in ("a", "button"):
                    self.open = [tag, "", a.get("aria-label") or a.get("title")]

            def handle_endtag(self, tag):
                if tag == "label":
                    self.depth -= 1
                if tag in ("a", "button") and self.open:
                    if not self.open[1].strip() and not self.open[2]:
                        self.bad.append(f"{tag} sem nome")
                    self.open = None

            def handle_data(self, data):
                if self.open:
                    self.open[1] += data

        p = P()
        p.feed(html)
        return p.bad + [f"campo sem rótulo: {n or i}" for i, aria, wrapped, n in p.fields
                        if not (aria or wrapped or (i and i in p.fors))]

    def test_new_screens_have_labels_and_names(self):
        self.login(self.prof)
        for url in (reverse("cognitio:student_projection", args=[self.ana.pk]) + f"?habilidade={self.h2.pk}",
                    reverse("cognitio:assistant") + f"?turma={self.cg.pk}",
                    reverse("cognitio:class_council", args=[self.cg.pk]),
                    reverse("cognitio:skill_graph", args=[self.h2.pk]) + f"?turma={self.cg.pk}",
                    reverse("cognitio:my_judgments")):
            self.assertEqual(self.audit(self.client.get(url).content.decode()), [], url)
