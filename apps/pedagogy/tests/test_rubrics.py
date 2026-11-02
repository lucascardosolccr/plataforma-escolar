"""Rubricas de avaliação (P9-20): cadastro, uso na atividade, avaliação e privacidade."""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from ..models import Activity, Rubric, RubricScore
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
