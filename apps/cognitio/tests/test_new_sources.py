"""Novas fontes de evidência do EIA-Cognitio: rubrica ligada a habilidade, exercício de prática e diário."""

import datetime as dt

from django.urls import reverse
from django.utils import timezone

from apps.cognitio.evidence import W_GROUP, W_PRACTICE, W_RUBRIC, rebuild_class
from apps.cognitio.models import SkillEvidence
from apps.communication.tests.test_communication import CommunicationBase
from apps.curriculum.models import CurriculumItem
from apps.pedagogy.models import (Activity, GroupWork, GroupWorkRubricScore, LessonRecord, Rubric, RubricCriterion,
                                  RubricLevel, RubricScore, WorkGroup, WorkGroupMember)


class NewSourcesBase(CommunicationBase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.h1 = CurriculumItem.objects.get(school__isnull=True, code="EF01MA01")
        self.h2 = CurriculumItem.objects.get(school__isnull=True, code="EF01MA02")
        self.rubric = Rubric.objects.create(school=self.school, title="Resolução de problemas", created_by=self.prof)
        self.levels = [RubricLevel.objects.create(rubric=self.rubric, label=l, order=i)
                       for i, l in enumerate(("Ainda não", "Em parte", "Atingiu"))]
        self.c_skill = RubricCriterion.objects.create(rubric=self.rubric, name="Contagem", order=0, item=self.h1)
        self.c_plain = RubricCriterion.objects.create(rubric=self.rubric, name="Capricho", order=1)

    def evidence(self, **kw):
        return SkillEvidence.objects.filter(student=self.ana, **kw)


class RubricEvidenceTests(NewSourcesBase):
    def test_activity_rubric_criterion_becomes_evidence_by_level_position(self):
        act = Activity.objects.create(school=self.school, class_group=self.turma, subject=self.mat, title="Contar",
                                      status="publicada", created_by=self.prof, rubric=self.rubric,
                                      class_date=self.today, published_date=self.today)
        RubricScore.objects.create(activity=act, student=self.ana, criterion=self.c_skill, level=self.levels[1])
        RubricScore.objects.create(activity=act, student=self.ana, criterion=self.c_plain, level=self.levels[2])
        rebuild_class(self.turma)
        ev = self.evidence(source_type="rubrica")
        self.assertEqual(ev.count(), 1)  # só o critério ligado a habilidade
        e = ev.get()
        self.assertEqual((e.item, e.ratio, e.weight), (self.h1, 0.5, W_RUBRIC))
        self.assertIn("Rubrica: Contagem", e.source_label)

    def test_group_rubric_goes_to_members_with_group_weight(self):
        work = GroupWork.objects.create(school=self.school, class_group=self.turma, subject=self.mat, title="Maquete",
                                        description="x", status="publicada", created_by=self.prof, rubric=self.rubric,
                                        published_date=self.today)
        group = WorkGroup.objects.create(group_work=work, name="Grupo 1")
        WorkGroupMember.objects.create(group=group, student=self.ana)
        gs = GroupWorkRubricScore.objects.create(group_work=work, group=group, criterion=self.c_skill,
                                                 level=self.levels[2])
        # Uma rubrica de atividade com o MESMO id não pode apagar a do trabalho (origens separadas).
        act = Activity.objects.create(school=self.school, class_group=self.turma, subject=self.mat, title="Contar",
                                      status="publicada", created_by=self.prof, rubric=self.rubric,
                                      class_date=self.today, published_date=self.today)
        RubricScore.objects.create(pk=gs.pk, activity=act, student=self.ana, criterion=self.c_skill,
                                   level=self.levels[0])
        rebuild_class(self.turma)
        self.assertEqual(self.evidence(source_type="rubrica").get().ratio, 0.0)
        e = self.evidence(source_type="rubrica_trab").get()
        self.assertEqual((e.ratio, e.weight), (1.0, W_GROUP))
        self.assertIn("Rubrica do grupo", e.source_label)

    def test_editor_saves_and_validates_skill_codes(self):
        self.login("prof")
        data = {"title": "Leitura", "description": "", "subject": self.mat.pk,
                "nivel_0": "Ainda não", "nivel_1": "Atingiu", "criterio_0": "Localiza informação",
                "habilidade_0": "ef01ma02", "criterio_1": "Outro", "habilidade_1": ""}
        self.client.post(reverse("pedagogy:rubric_create"), data)
        r = Rubric.objects.get(title="Leitura")
        self.assertEqual([c.item for c in r.criteria.order_by("order")], [self.h2, None])
        data.update(title="Errada", habilidade_0="EF99XX99")
        resp = self.client.post(reverse("pedagogy:rubric_create"), data)
        self.assertContains(resp, "não encontrado no catálogo: EF99XX99")
        self.assertFalse(Rubric.objects.filter(title="Errada").exists())


class PracticeAndDiaryTests(NewSourcesBase):
    def test_only_the_first_practice_attempt_counts_with_low_weight(self):
        from apps.study.models import ExamGuide, PracticeAttempt, PracticeQuestion

        guide = ExamGuide.objects.create(school=self.school, class_group=self.turma, subject=self.mat,
                                         title="Prova de números", exam_date=self.today + dt.timedelta(days=7),
                                         created_by=self.prof)
        q = PracticeQuestion.objects.create(guide=guide, statement="Quanto é 2+2?", options=["3", "4"], correct=1)
        q.curriculum.add(self.h1)
        PracticeAttempt.objects.create(question=q, student=self.ana, chosen=0, is_correct=False)
        PracticeAttempt.objects.create(question=q, student=self.ana, chosen=1, is_correct=True)  # tentou de novo
        rebuild_class(self.turma)
        e = self.evidence(source_type="pratica").get()
        self.assertEqual((e.item, e.ratio, e.weight), (self.h1, 0.0, W_PRACTICE))

    def test_diary_counts_as_worked_for_the_not_evaluated_list(self):
        from apps.cognitio.views_dash import not_evaluated_for

        rec = LessonRecord.objects.create(school=self.school, class_group=self.turma, subject=self.mat,
                                          teacher=self.prof, date=self.today, content="Contagem")
        rec.curriculum.add(self.h2)
        rows = not_evaluated_for(self.prof, today=self.today)["rows"]
        self.assertIn((self.h2, "diário"), [(r["item"], r["origin"]) for r in rows])
