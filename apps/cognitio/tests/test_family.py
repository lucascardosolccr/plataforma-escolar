"""Resumo de aprendizagens para a família e o estudante; pendências do EIA-Cognitio."""

from django.urls import reverse

from apps.cognitio.alerts import generate_for_class
from apps.cognitio.evidence import rebuild_class
from apps.cognitio.models import MasteryScale, SkillObservation, TextAnalysis
from apps.cognitio.tests.test_evidence import Base
from apps.core.models import Role, User
from apps.registry.models import GuardianLink


class FamilySummaryTests(Base):
    def setUp(self):
        super().setUp()
        for lvl in (1, 1):
            SkillObservation.objects.create(school=self.school, student=self.ana, item=self.h1, class_group=self.cg,
                                            subject=self.mat, teacher=self.prof, level=lvl, context="Sala")
        for lvl in (5, 5):
            SkillObservation.objects.create(school=self.school, student=self.ana, item=self.h2, class_group=self.cg,
                                            subject=self.mat, teacher=self.prof, level=lvl, context="Sala")
        TextAnalysis.objects.create(school=self.school, student=self.ana, class_group=self.cg, subject=self.mat,
                                    title="Resposta Q3", text="x", reviewed=True, teacher_feedback="Ótimo raciocínio!")
        TextAnalysis.objects.create(school=self.school, student=self.ana, class_group=self.cg, subject=self.mat,
                                    title="Rascunho", text="y", reviewed=False, teacher_feedback="Nota interna")
        rebuild_class(self.cg)
        self.url = reverse("cognitio:family_summary", args=[self.ana.pk])

    def test_off_by_default_then_family_language(self):
        self.login(self.fam)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertNotContains(self.client.get(reverse("student_detail", args=[self.ana.pk])), self.url)
        MasteryScale.objects.create(school=self.school, share_with_family=True)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        c = r.context["comps"]["Matemática"]
        self.assertEqual(([i.code for i in c["done"]], [i.code for i in c["developing"]]), (["EF06MA03"], ["EF06MA01"]))
        self.assertNotContains(r, "ificuldade")  # a família não recebe o rótulo "dificuldade"
        self.assertNotContains(r, "%")
        self.assertContains(r, "Ótimo raciocínio!")
        self.assertNotContains(r, "Nota interna")  # devolutiva só depois da revisão
        self.assertContains(self.client.get(reverse("student_detail", args=[self.ana.pk])), self.url)

    def test_coordination_turns_it_on_in_the_scale_form(self):
        self.login(self.coord)
        self.assertContains(self.client.get(reverse("cognitio:scale")), "share_with_family")
        self.client.post(reverse("cognitio:scale"), {"t1": "0.3", "t2": "0.5", "t3": "0.7", "min_evidence": 2,
                                                      "min_weight": "1.2", "half_life_days": 90, "stale_days": 60,
                                                      "share_with_family": "on"})
        self.assertTrue(MasteryScale.objects.get(school=self.school).share_with_family)
        self.login(self.fam)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_who_can_see(self):
        MasteryScale.objects.create(school=self.school, share_with_family=True)
        aluna = User.objects.create_user("ana.aluna", password="Senha-forte-123", role=Role.ESTUDANTE,
                                         school=self.school)
        self.ana.user = aluna
        self.ana.save()
        other_fam = User.objects.create_user("fam2", password="Senha-forte-123", role=Role.RESPONSAVEL,
                                             school=self.school)
        GuardianLink.objects.create(school=self.school, guardian=other_fam, student=self.bia, status="aprovado")
        self.login(aluna)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.get(reverse("cognitio:family_summary", args=[self.bia.pk])).status_code, 403)
        for user in (other_fam, self.prof, self.sec):
            self.login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403, user.username)


class PendingTests(Base):
    def test_teacher_sees_important_alerts_to_review(self):
        from datetime import timedelta

        for d in (40, 20, 2):
            SkillObservation.objects.create(school=self.school, student=self.ana, item=self.h1, class_group=self.cg,
                                            subject=self.mat, teacher=self.prof, level=1, context="Sala",
                                            observed_on=self.today - timedelta(days=d))
        rebuild_class(self.cg)
        generate_for_class(self.cg, self.today)
        self.login(self.prof)
        r = self.client.get(reverse("pending_center"))
        self.assertContains(r, "Alertas pedagógicos importantes para revisar")
        self.login(self.prof_b)
        self.assertNotContains(self.client.get(reverse("pending_center")), "Alertas pedagógicos importantes")
