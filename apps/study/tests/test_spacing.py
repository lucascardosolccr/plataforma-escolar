"""Revisão espaçada dos exercícios de prática: intervalos, véspera da prova, primeira resposta do dia, intercalação."""

import datetime as dt
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from .. import spacing
from ..models import ExamTopic, PracticeAttempt, PracticeQuestion
from .test_study import StudyBase

TODAY = dt.date(2026, 11, 2)
EXAM = dt.date(2026, 11, 30)


def att(day, correct, hour=10, q=1):
    return SimpleNamespace(question_id=q, is_correct=correct,
                           created_at=timezone.make_aware(dt.datetime.combine(day, dt.time(hour))))


class ScheduleTests(SimpleTestCase):
    def test_new_and_first_review(self):
        self.assertEqual(spacing.state([], EXAM, TODAY)["state"], "novo")
        s = spacing.state([att(TODAY, True)], EXAM, TODAY)
        self.assertEqual((s["state"], s["due"]), ("agendado", TODAY + dt.timedelta(days=2)))
        s = spacing.state([att(TODAY, False)], EXAM, TODAY)
        self.assertEqual(s["due"], TODAY + dt.timedelta(days=1))  # errou: volta amanhã

    def test_intervals_grow_with_successive_correct_days(self):
        days = [TODAY - dt.timedelta(days=d) for d in (9, 7, 3)]
        s = spacing.state([att(d, True) for d in days], EXAM, TODAY)
        self.assertEqual(s["box"], 3)
        self.assertEqual(s["due"], days[-1] + dt.timedelta(days=7))
        s = spacing.state([att(d, True) for d in days] + [att(TODAY, False)], EXAM, TODAY)
        self.assertEqual((s["box"], s["due"]), (0, TODAY + dt.timedelta(days=1)))

    def test_only_the_first_answer_of_the_day_counts(self):
        s = spacing.state([att(TODAY, False, 9), att(TODAY, True, 10)], EXAM, TODAY)
        self.assertEqual(s["box"], 0)  # acertou depois de ver o gabarito: reestudo, não recuperação
        self.assertEqual(s["days"], 1)

    def test_never_past_the_eve_of_the_exam(self):
        exam = TODAY + dt.timedelta(days=3)
        days = [TODAY - dt.timedelta(days=d) for d in (6, 4, 0)]
        s = spacing.state([att(d, True) for d in days], exam, TODAY)
        self.assertEqual(s["due"], exam - dt.timedelta(days=1))
        s = spacing.state([att(TODAY, True)], TODAY + dt.timedelta(days=1), TODAY)
        self.assertEqual(s["state"], "concluido")  # prova amanhã: não há revisão antes dela
        s = spacing.state([att(TODAY - dt.timedelta(days=5), True)], TODAY - dt.timedelta(days=1), TODAY)
        self.assertEqual(s["state"], "concluido")

    def test_today_list_interleaves_topics(self):
        qs = [SimpleNamespace(pk=i, topic_id=t) for i, t in ((1, "a"), (2, "a"), (3, "a"), (4, "b"), (5, "b"))]
        p = spacing.plan(qs, [], EXAM, TODAY)
        self.assertEqual([q.topic_id for q in p["new"]], ["a", "b", "a", "b", "a"])


class SpacedPracticeScreenTests(StudyBase):
    def test_student_sees_what_to_review_and_teacher_sees_distributed_practice(self):
        g = self.guide()
        q1 = PracticeQuestion.objects.create(guide=g, topic=self.topic, statement="3 × 4?", options=["7", "12"],
                                             correct=1)
        other = ExamTopic.objects.create(guide=g, title="Frações", priority="media")
        PracticeQuestion.objects.create(guide=g, topic=other, statement="1/2 + 1/2?", options=["1", "2"], correct=0)
        self.login(self.conta)
        page = self.client.get(reverse("study:detail", args=[g.pk]))
        self.assertContains(page, "Para revisar hoje")
        self.assertContains(page, "Operações · novo")
        self.assertContains(page, "Frações · novo")
        self.client.post(reverse("study:practice_answer", args=[g.pk, q1.pk]), {"alternativa": "1"})
        page = self.client.get(reverse("study:detail", args=[g.pk]))
        due = self.today + dt.timedelta(days=2)
        self.assertContains(page, f"próxima revisão {due:%d/%m}")
        self.assertNotContains(page, "Operações · novo")
        # Na hora da revisão, a resposta anterior e a explicação ficam escondidas: é recuperação, não releitura.
        PracticeQuestion.objects.filter(pk=q1.pk).update(explanation="Três grupos de quatro.")
        PracticeAttempt.objects.filter(question=q1).update(created_at=timezone.now() - dt.timedelta(days=2))
        page = self.client.get(reverse("study:detail", args=[g.pk]))
        self.assertContains(page, "Hora de revisar: responda de cabeça")
        self.assertNotContains(page, "Três grupos de quatro.")
        self.assertNotContains(page, " checked>")
        # Mesmo exercício respondido num dia anterior: 2 dias distintos de prática.
        PracticeAttempt.objects.filter(question=q1).update(
            created_at=timezone.now() - dt.timedelta(days=3))
        self.client.post(reverse("study:practice_answer", args=[g.pk, q1.pk]), {"alternativa": "1"})
        self.login(self.prof)
        page = self.client.get(reverse("study:detail", args=[g.pk]))
        self.assertContains(page, "Prática distribuída:</strong> dos 1 estudante que já praticaram, 1 respondeu em 2 dias")
