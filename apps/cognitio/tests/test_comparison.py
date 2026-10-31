"""Comparação descritiva do resultado de uma intervenção com colegas da mesma turma."""

from datetime import timedelta

from django.urls import reverse

from apps.academics.models import SchoolYear
from apps.cognitio.evidence import rebuild_class
from apps.cognitio.models import LearningIntervention, SkillObservation
from apps.cognitio.recommend import comparison
from apps.cognitio.tests.test_evidence import Base
from apps.registry.models import Enrollment, Student


class ComparisonTests(Base):
    def setUp(self):
        super().setUp()
        year = SchoolYear.objects.get(school=self.school)
        for name in ("Davi", "Eva", "Fabi", "Gil", "Hugo"):
            s = Student.objects.create(school=self.school, first_name=name)
            Enrollment.objects.create(school=self.school, student=s, class_group=self.cg, school_year=year)
            self.students.append(s)
        self.start = self.today - timedelta(days=20)
        self.iv = LearningIntervention.objects.create(
            school=self.school, class_group=self.cg, subject=self.mat, item=self.h1, title="Retomada",
            objective="o", activity="a", starts_on=self.start, review_on=self.today, created_by=self.prof)

    def obs(self, student, before, after):
        for lvl, days in ((before, 30), (before, 25), (after, 10), (after, 5)):
            SkillObservation.objects.create(school=self.school, student=student, item=self.h1, class_group=self.cg,
                                            subject=self.mat, teacher=self.prof, level=lvl, context="Sala",
                                            observed_on=self.today - timedelta(days=days))

    def test_gain_against_similar_classmates_only_in_aggregate(self):
        ana, bia, caio, davi, eva, fabi, gil, hugo = self.students
        self.iv.students.set([ana, bia, caio])
        for s in (ana, bia, caio):
            self.obs(s, 2, 4)
        for s in (davi, eva, fabi):
            self.obs(s, 2, 3)
        self.obs(gil, 5, 5)  # começou muito acima: fica fora da comparação
        rebuild_class(self.cg)
        c = comparison(self.iv)
        self.assertTrue(c["enough"])
        self.assertEqual((c["n_part"], c["n_comp"]), (3, 3))
        self.assertGreater(c["gain_part"], c["gain_comp"])
        self.assertAlmostEqual(c["difference"], c["gain_part"] - c["gain_comp"], places=2)
        self.login(self.prof)
        r = self.client.get(reverse("cognitio:intervention_detail", args=[self.iv.pk]))
        self.assertContains(r, "Comparação com colegas da turma")
        self.assertContains(r, "não prova de efeito")
        self.assertNotContains(r, "Davi")  # colegas da comparação aparecem só em número

    def test_small_groups_are_not_compared(self):
        ana, bia, caio, davi, eva = self.students[:5]
        self.iv.students.set([ana, bia])
        for s in (ana, bia, davi, eva, caio):
            self.obs(s, 2, 3)
        rebuild_class(self.cg)
        c = comparison(self.iv)
        self.assertFalse(c["enough"])
        self.assertEqual((c["n_part"], c["n_comp"]), (2, 3))
        self.login(self.prof)
        self.assertContains(self.client.get(reverse("cognitio:intervention_detail", args=[self.iv.pk])),
                            "Ainda não dá para comparar")
