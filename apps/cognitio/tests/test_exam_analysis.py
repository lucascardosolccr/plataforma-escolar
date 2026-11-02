"""Análise da prova depois da correção (Prompt 18 §10.10)."""

from decimal import Decimal

from django.urls import reverse

from apps.cognitio.models import Question, QuestionResponse, QuestionSkill, SkillRelation
from apps.core.models import AuditLog
from apps.curriculum.models import CurriculumItem
from apps.registry.models import Enrollment, Student
from apps.study.models import ExamGuide, ExamTopic, StudyMaterial

from .test_evidence import Base

ANSWERED, BLANK, ABSENT = (QuestionResponse.Status.ANSWERED, QuestionResponse.Status.BLANK,
                           QuestionResponse.Status.ABSENT)


class ExamAnalysisTests(Base):
    def setUp(self):
        super().setUp()
        year = self.cg.school_year
        self.duda = Student.objects.create(school=self.school, first_name="Duda")
        self.eva = Student.objects.create(school=self.school, first_name="Eva")
        for s in (self.duda, self.eva):
            Enrollment.objects.create(school=self.school, student=s, class_group=self.cg, school_year=year)
        self.url = reverse("cognitio:exam_analysis", args=[self.ev.pk])

    def question(self, n, main, secondary=None, max_points="2"):
        q = Question.objects.create(evaluation=self.ev, number=n, label=f"Questão {n}", max_points=Decimal(max_points))
        QuestionSkill.objects.create(question=q, item=main, role="principal")
        if secondary:
            QuestionSkill.objects.create(question=q, item=secondary, role="secundaria")
        return q

    def answer(self, q, student, points=None, status=ANSWERED, error=""):
        QuestionResponse.objects.create(question=q, student=student, status=status,
                                        points=None if points is None else Decimal(points), error_type=error)

    def scenario(self):
        """h1 em duas questões; h2 numa só, que quase ninguém acertou."""
        q1, q2, q3 = self.question(1, self.h1), self.question(2, self.h1), self.question(3, self.h2)
        for q in (q1, q2):
            self.answer(q, self.ana, "2")
            self.answer(q, self.bia, "0", error="conceitual")
            self.answer(q, self.caio, status=ABSENT)
            self.answer(q, self.duda, "1")
            self.answer(q, self.eva, status=BLANK)
        for s in self.students + [self.duda, self.eva]:
            self.answer(q3, s, "0")
        return q1, q2, q3

    def test_levels_single_question_review_and_absence(self):
        self.scenario()
        self.login(self.prof)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        rows = {row["item"].pk: row for row in r.context["a"]["skills"]}
        h1 = {code: n for code, _, n in rows[self.h1.pk]["counts"]}
        # Ausente não é erro; em branco conta como zero.
        self.assertEqual(h1, {"demonstrou": 1, "parcial": 1, "nao_demonstrou": 2, "sem_registro": 1})
        self.assertEqual({s.first_name for s in rows[self.h1.pk]["not_dem"]}, {"Bia", "Eva"})
        self.assertTrue(rows[self.h1.pk]["group"])
        # Uma questão só: aviso, e nada de grupo de apoio por ela.
        self.assertTrue(rows[self.h2.pk]["single"])
        self.assertFalse(rows[self.h2.pk]["group"])
        self.assertContains(r, "Uma questão só: não basta para concluir.")
        self.assertContains(r, "Medida por uma questão só")
        # Questão que ninguém acertou é revisada antes de virar conclusão.
        self.assertContains(r, "Quase ninguém acertou")
        self.assertEqual(sum(1 for q in r.context["a"]["questions"] if q["review"]), 1)
        self.assertTrue(r.context["a"]["errors"])
        self.assertContains(r, f"habilidade={self.h1.pk}&tipo=recuperacao&estudante=")

    def test_prerequisites_are_flagged_as_unvalidated_and_counted_by_evidence(self):
        pre = CurriculumItem.objects.get(code="EF06MA02")
        SkillRelation.objects.create(school=self.school, source=pre, target=self.h1, kind="prerequisito",
                                     status="proposta", rationale="teste")
        self.scenario()
        self.login(self.prof)
        r = self.client.get(self.url)
        row = next(x for x in r.context["a"]["skills"] if x["item"].pk == self.h1.pk)
        by_code = {p["rel"].source.code: p for p in row["prereqs"]}  # mais as progressões nacionais do grafo
        self.assertEqual(by_code["EF06MA02"]["tally"]["sem_evidencia"], 3)  # Bia, Eva e Duda: sem registro
        self.assertContains(r, "relação proposta, a confirmar pela escola")
        self.assertContains(r, "sem evidência em 3")

    def test_retake_topics_and_individual_support(self):
        q1, q2 = self.question(1, self.h1), self.question(2, self.h1)
        q3, q4 = self.question(3, self.h2), self.question(4, self.h2)
        for q in (q1, q2, q3, q4):
            self.answer(q, self.bia, "0")
            self.answer(q, self.ana, "2")
            self.answer(q, self.caio, "0")
        guide = ExamGuide.objects.create(school=self.school, class_group=self.cg, subject=self.mat, evaluation=self.ev,
                                         title="Preparação P1", exam_date=self.ev.date, created_by=self.prof,
                                         status="publicado")
        topic = ExamTopic.objects.create(guide=guide, title="Números naturais")
        topic.curriculum.add(self.h1)
        StudyMaterial.objects.create(guide=guide, topic=topic, kind="resumo", title="Resumo de sistema decimal",
                                     created_by=self.prof)
        StudyMaterial.objects.create(guide=guide, topic=topic, kind="resumo", title="Material retirado",
                                     created_by=self.prof, removed_at=guide.created_at)
        self.login(self.prof)
        r = self.client.get(self.url)
        self.assertContains(r, "Números naturais")
        self.assertContains(r, "Resumo de sistema decimal")
        self.assertNotContains(r, "Material retirado")
        self.assertEqual({s.first_name for s, _ in r.context["a"]["support"]}, {"Bia", "Caio"})
        # A tela da prova leva à análise.
        page = self.client.get(reverse("study:detail", args=[guide.pk]))
        self.assertContains(page, reverse("cognitio:exam_analysis", args=[self.ev.pk]))

    def test_access_scope_and_audit(self):
        self.scenario()
        for user, status in ((self.prof, 200), (self.prof_b, 403), (self.prof_geo, 403), (self.coord, 200),
                             (self.coord_b, 403), (self.dir, 200), (self.sec, 403), (self.fam, 403)):
            self.login(user)
            self.assertEqual(self.client.get(self.url).status_code, status, user.username)
        audited = set(AuditLog.objects.filter(action="view", detail__startswith="Consultou a análise da prova")
                      .values_list("user__username", flat=True))
        self.assertEqual(audited, {"coord", "dir"})  # o professor da turma não é registrado

    def test_without_results_and_without_questions(self):
        self.login(self.prof)
        r = self.client.get(self.url)
        self.assertContains(r, "Ainda não há resultados por questão")
        guide = ExamGuide.objects.create(school=self.school, class_group=self.cg, subject=self.mat, evaluation=self.ev,
                                         title="Preparação P1", exam_date=self.ev.date, created_by=self.prof)
        page = self.client.get(reverse("study:detail", args=[guide.pk]))
        self.assertContains(page, "Cadastrar as questões")
