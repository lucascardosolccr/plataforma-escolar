"""Rubricas de avaliação (P9-20): cadastro, uso na atividade, avaliação e privacidade."""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from ..models import (Activity, GroupWork, GroupWorkRubricScore, Rubric, RubricCriterion, RubricLevel,
                      RubricScore)
from .test_group_work import GroupWorkBase
from .test_pedagogy import PedagogyBase


class RubricTests(PedagogyBase):
    def make_rubric(self, user="prof"):
        self.login(user)
        data = {"title": "Produção de texto", "shared": "on",
                "nivel_0": "Ainda não", "nivel_1": "Em parte", "nivel_2": "Atingiu", "pontos_2": "2",
                "criterio_0": "Organização", "desc_0_0": "Ideias soltas", "desc_0_2": "Começo, meio e fim",
                "criterio_1": "Ortografia"}
        r = self.client.post(reverse("pedagogy:rubric_create"), data)
        self.assertEqual(r.status_code, 302)
        return Rubric.objects.get()

    def activity(self, rubric):
        return Activity.objects.create(school=self.school, class_group=self.turma, subject=self.mat,
                                       title="Redação", description="Escreva.", created_by=self.prof,
                                       status=Activity.Status.PUBLISHED, rubric=rubric,
                                       published_date=timezone.localdate() - timedelta(days=1))

    def test_create_validates_the_grid(self):
        self.login("prof")
        r = self.client.post(reverse("pedagogy:rubric_create"), {"title": "X", "nivel_0": "Só um",
                                                                 "criterio_0": "C"})
        self.assertContains(r, "pelo menos dois níveis")
        rubric = self.make_rubric()
        levels, rows = rubric.grid()
        self.assertEqual([lv.label for lv in levels], ["Ainda não", "Em parte", "Atingiu"])
        self.assertEqual(rows[0][1], ["Ideias soltas", "", "Começo, meio e fim"])

    def test_only_teachers_create(self):
        for user in ("coord", "resp", "sec"):
            self.login(user)
            self.assertEqual(self.client.get(reverse("pedagogy:rubric_create")).status_code, 403, user)

    def test_scoring_and_family_sees_only_own_child(self):
        rubric = self.make_rubric()
        act = self.activity(rubric)
        crit = rubric.criteria.get(name="Organização")
        top = rubric.levels.get(label="Atingiu")
        r = self.client.post(reverse("pedagogy:activity_rubric_scores", args=[act.pk]),
                             {f"r_{self.ana.pk}_{crit.pk}": top.pk})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(RubricScore.objects.get().level, top)
        self.login("resp")
        page = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        self.assertContains(page, "Como será avaliada: Produção de texto")
        self.assertContains(page, "Organização: Atingiu")
        # Outro professor não avalia; nível de outra rubrica é recusado.
        self.login("prof2")
        self.assertEqual(self.client.get(reverse("pedagogy:activity_rubric_scores", args=[act.pk])).status_code, 403)

    def test_rubric_in_use_cannot_be_edited_only_duplicated(self):
        rubric = self.make_rubric()
        act = self.activity(rubric)
        crit = rubric.criteria.first()
        RubricScore.objects.create(activity=act, student=self.ana, criterion=crit, level=rubric.levels.first())
        r = self.client.get(reverse("pedagogy:rubric_edit", args=[rubric.pk]))
        self.assertEqual(r.status_code, 302)
        r = self.client.get(reverse("pedagogy:rubric_duplicate", args=[rubric.pk]))
        self.assertContains(r, "Produção de texto (cópia)")

    def test_activity_form_offers_own_and_shared_rubrics_only(self):
        shared = self.make_rubric()
        private = Rubric.objects.create(school=self.school, title="Privada do prof2", created_by=self.prof2)
        self.login("prof")
        form = self.client.get(reverse("pedagogy:activity_create")).context["form"]
        self.assertIn(shared, form.fields["rubric"].queryset)
        self.assertNotIn(private, form.fields["rubric"].queryset)


class GroupWorkRubricTests(GroupWorkBase):
    """Rubrica no trabalho em grupo: nível do grupo (modo grupo) ou de cada integrante (modo individual)."""

    def rubric(self):
        r = Rubric.objects.create(school=self.school, title="Apresentação oral", created_by=self.prof)
        self.crit = RubricCriterion.objects.create(rubric=r, name="Clareza", order=0)
        self.low = RubricLevel.objects.create(rubric=r, label="Em parte", order=0)
        self.top = RubricLevel.objects.create(rubric=r, label="Atingiu", order=1)
        return r

    def test_group_mode_scores_the_group_and_family_sees_it_as_group(self):
        work = self.make_work(rubric=self.rubric(), delivery_mode=GroupWork.DeliveryMode.GROUP)
        g1 = self.make_group(work, "Grupo 1", [self.ana, self.bruno])
        g2 = self.make_group(work, "Grupo 2", [self.carla, self.davi])
        self.login("prof")
        url = reverse("pedagogy:group_work_rubric_scores", args=[work.pk])
        page = self.client.get(url)
        self.assertContains(page, "por grupo")
        self.assertContains(page, f'name="r_g{g1.pk}_{self.crit.pk}"')
        self.assertNotContains(page, f'name="r_s{self.ana.pk}_{self.crit.pk}"')
        self.client.post(url, {f"r_g{g1.pk}_{self.crit.pk}": self.top.pk, f"r_g{g2.pk}_{self.crit.pk}": self.low.pk})
        score = GroupWorkRubricScore.objects.get(group=g1)
        self.assertIsNone(score.student_id)
        self.assertEqual(GroupWorkRubricScore.objects.count(), 2)
        detail = self.client.get(reverse("pedagogy:group_work_detail", args=[work.pk]))
        self.assertContains(detail, "Avaliar com a rubrica")
        self.assertContains(detail, "Como será avaliado: Apresentação oral (por grupo)")
        self.login("resp_ana")
        detail = self.client.get(reverse("pedagogy:group_work_detail", args=[work.pk]))
        self.assertContains(detail, "Avaliação do grupo de Ana pela rubrica")
        self.assertContains(detail, "Clareza: Atingiu")
        self.assertNotContains(detail, "Clareza: Em parte")  # nível do outro grupo
        self.assertNotContains(detail, "Avaliar com a rubrica")

    def test_individual_mode_scores_each_member(self):
        work = self.make_work(rubric=self.rubric(), delivery_mode=GroupWork.DeliveryMode.INDIVIDUAL)
        self.make_group(work, "Grupo 1", [self.ana, self.bruno])
        self.login("prof")
        url = reverse("pedagogy:group_work_rubric_scores", args=[work.pk])
        self.client.post(url, {f"r_s{self.ana.pk}_{self.crit.pk}": self.top.pk,
                               f"r_s{self.bruno.pk}_{self.crit.pk}": self.low.pk})
        self.assertEqual(GroupWorkRubricScore.objects.get(student=self.ana).level, self.top)
        self.login("resp_bruno")
        detail = self.client.get(reverse("pedagogy:group_work_detail", args=[work.pk]))
        self.assertContains(detail, "Avaliação de Bruno pela rubrica")
        self.assertContains(detail, "Clareza: Em parte")
        self.assertNotContains(detail, "Clareza: Atingiu")  # nível da Ana não vaza

    def test_other_teacher_and_family_cannot_score_and_canceled_is_read_only(self):
        work = self.make_work(rubric=self.rubric())
        g1 = self.make_group(work, "Grupo 1", [self.ana])
        url = reverse("pedagogy:group_work_rubric_scores", args=[work.pk])
        for user in ("prof2", "resp_ana", "aluno_ana"):
            self.login(user)
            self.assertIn(self.client.get(url).status_code, (403, 404), user)
            self.client.post(url, {f"r_g{g1.pk}_{self.crit.pk}": self.top.pk})
        self.assertFalse(GroupWorkRubricScore.objects.exists())
        work.status = GroupWork.Status.CANCELED
        work.save(update_fields=["status"])
        self.login("prof")
        self.assertContains(self.client.get(url), "Trabalho cancelado")
        self.client.post(url, {f"r_g{g1.pk}_{self.crit.pk}": self.top.pk})
        self.assertFalse(GroupWorkRubricScore.objects.exists())

    def test_level_from_another_rubric_is_ignored(self):
        work = self.make_work(rubric=self.rubric())
        g1 = self.make_group(work, "Grupo 1", [self.ana])
        other = Rubric.objects.create(school=self.school, title="Outra", created_by=self.prof)
        foreign = RubricLevel.objects.create(rubric=other, label="X", order=0)
        self.login("prof")
        self.client.post(reverse("pedagogy:group_work_rubric_scores", args=[work.pk]),
                         {f"r_g{g1.pk}_{self.crit.pk}": foreign.pk})
        self.assertFalse(GroupWorkRubricScore.objects.exists())
