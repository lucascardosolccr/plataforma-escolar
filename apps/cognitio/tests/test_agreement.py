"""Concordância entre observadores (agreement.py e a tela de coordenação)."""

from datetime import timedelta

from django.urls import reverse

from apps.cognitio import agreement
from apps.cognitio.models import SkillObservation
from apps.cognitio.tests.test_evidence import Base


class AgreementServiceTests(Base):
    def obs(self, student, item, teacher, level, day=None, subject=None):
        return SkillObservation.objects.create(
            school=self.school, student=student, item=item, class_group=self.cg,
            subject=subject or self.mat, teacher=teacher, level=level, context="Sala",
            observed_on=day or self.today)

    def test_pairs_only_across_teachers_and_within_window(self):
        # Mesma ocasião, dois professores: um par.
        self.obs(self.ana, self.h1, self.prof, 4)
        self.obs(self.ana, self.h1, self.prof_b, 4)
        # Mesmo professor duas vezes: não vira par entre avaliadores.
        self.obs(self.bia, self.h1, self.prof, 3)
        self.obs(self.bia, self.h1, self.prof, 5)
        # Dois professores, mas a 40 dias: ocasiões diferentes, sem par.
        self.obs(self.caio, self.h1, self.prof, 2)
        self.obs(self.caio, self.h1, self.prof_b, 5, day=self.today + timedelta(days=40))
        r = agreement.summary(self.school, self.today - timedelta(days=90), self.today + timedelta(days=90),
                              min_pairs=1)
        self.assertEqual(r["pairs"], 1)
        self.assertEqual(r["occasions"], 1)
        self.assertEqual(r["percent"]["exact"], 1.0)

    def test_insufficient_pairs(self):
        self.obs(self.ana, self.h1, self.prof, 4)
        self.obs(self.ana, self.h1, self.prof_b, 3)
        r = agreement.summary(self.school, self.today - timedelta(days=30), self.today + timedelta(days=30))
        self.assertFalse(r["enough"])
        self.assertEqual(r["pairs"], 1)

    def test_coefficients_and_discordant_list(self):
        # 12 pares concordantes + 1 par bem discordante (nível 1 vs 5).
        for i, st in enumerate(self.students * 4):
            self.obs(st, self.h1, self.prof, 4, day=self.today + timedelta(days=i))
            self.obs(st, self.h1, self.prof_b, 4, day=self.today + timedelta(days=i))
        self.obs(self.ana, self.h2, self.prof, 1, day=self.today + timedelta(days=60))
        self.obs(self.ana, self.h2, self.prof_b, 5, day=self.today + timedelta(days=60))
        r = agreement.summary(self.school, self.today - timedelta(days=5), self.today + timedelta(days=120),
                              window=1, min_pairs=12)
        self.assertTrue(r["enough"])
        self.assertEqual(r["pairs"], 13)
        self.assertGreater(r["percent"]["exact"], 0.9)
        self.assertEqual(r["discordant"][0]["gap"], 4)       # a ocasião 1×5 lidera
        self.assertEqual(r["discordant"][0]["item"], self.h2)

    def test_subject_and_student_scope_filters(self):
        self.obs(self.ana, self.h1, self.prof, 4)
        self.obs(self.ana, self.h1, self.prof_b, 2)
        r = agreement.summary(self.school, self.today - timedelta(days=5), self.today + timedelta(days=5),
                              student_ids=[self.bia.pk], min_pairs=1)
        self.assertEqual(r["pairs"], 0)
        self.assertFalse(r["enough"])


class AgreementViewTests(Base):
    def test_access_and_render(self):
        url = reverse("cognitio:agreement")
        # Coordenação e direção entram.
        for user in (self.coord, self.dir):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, 200)
        # Professor, secretaria e família, não.
        for user in (self.prof, self.sec, self.fam):
            self.login(user)
            self.assertIn(self.client.get(url).status_code, (302, 403))

    def test_full_template_renders_with_data(self):
        for i, st in enumerate(self.students * 5):
            d = self.today - timedelta(days=i)
            SkillObservation.objects.create(school=self.school, student=st, item=self.h1, class_group=self.cg,
                                            subject=self.mat, teacher=self.prof, level=4, context="Sala", observed_on=d)
            SkillObservation.objects.create(school=self.school, student=st, item=self.h1, class_group=self.cg,
                                            subject=self.mat, teacher=self.prof_b, level=4, context="Sala", observed_on=d)
        self.login(self.coord)
        r = self.client.get(reverse("cognitio:agreement"), {"turma": self.cg.pk})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Concordância geral")
        self.assertContains(r, "AC2 de Gwet")
