"""Painéis do EIA-Cognitio por perfil e por disciplina (Prompt 16, etapa 9)."""

from django.urls import reverse

from apps.cognitio.evidence import rebuild_class
from apps.cognitio.models import Question, QuestionResponse, QuestionSkill, SkillObservation
from apps.cognitio.tests.test_evidence import Base
from apps.curriculum.models import CurriculumItem


class DashboardTests(Base):
    def setUp(self):
        super().setUp()
        for st, lvl in ((self.ana, 1), (self.ana, 1), (self.bia, 1), (self.bia, 2), (self.caio, 5), (self.caio, 5)):
            SkillObservation.objects.create(school=self.school, student=st, item=self.h1, class_group=self.cg,
                                            subject=self.mat, teacher=self.prof, level=lvl, context="Sala")
        q = Question.objects.create(evaluation=self.ev, number=1, label="Q1", max_points=1)
        QuestionSkill.objects.create(question=q, item=self.h2)
        QuestionResponse.objects.create(question=q, student=self.ana, points=0, error_type="conceitual")
        art = CurriculumItem.objects.filter(component="Arte", years__contains="6").first()
        from apps.academics.models import Subject

        self.arte = Subject.objects.create(school=self.school, name="Arte")
        SkillObservation.objects.create(school=self.school, student=self.ana, item=art, class_group=self.cg,
                                        subject=self.arte, teacher=self.prof, level=3, context="Ateliê")
        rebuild_class(self.cg)

    def test_teacher_coordination_and_direction(self):
        url = reverse("cognitio:dashboard")
        self.login(self.prof)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([d["item"].code for d in r.context["attention"]], ["EF06MA01"])
        self.assertContains(r, "Sugestões para as próximas aulas")
        self.login(self.coord)
        r = self.client.get(url)
        self.assertEqual([c["cg"].name for c in r.context["classes"]], ["6º Ano A"])
        self.login(self.dir)
        r = self.client.get(url)
        self.assertContains(r, "Oculto: menos de 5 estudantes")  # só 3 estudantes
        for name in ("Ana", "Bia", "Caio"):
            self.assertNotContains(r, name)
        self.assertIn("evals_skill", r.context["quality"])
        for user in (self.sec, self.fam):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_discipline_lenses(self):
        self.login(self.coord)
        url = reverse("cognitio:discipline")
        r = self.client.get(url + "?componente=Matemática")
        self.assertEqual(r.context["errors"][0][1], [("Erro conceitual", 1)])
        self.assertTrue(r.context["unit_rows"])
        r = self.client.get(url + "?componente=Arte")
        self.assertTrue(r.context["no_error_typing"])
        self.assertContains(r, "não classifica gosto, talento")
        self.login(self.prof_geo)
        r = self.client.get(url)
        self.assertEqual(r.context["comp_choices"], [])  # sem evidências de Geografia
