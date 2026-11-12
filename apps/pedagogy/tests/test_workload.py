"""Concentração de prazos (workload.py e a tela de planejamento)."""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from .. import workload
from ..models import Activity, Evaluation, GroupWork
from .test_pedagogy import PedagogyBase


class WorkloadServiceTests(PedagogyBase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()

    def _activity(self, when):
        return Activity.objects.create(school=self.school, class_group=self.turma, subject=self.mat,
                                       title="Lista", description="x", created_by=self.prof,
                                       status=Activity.Status.PUBLISHED, deadline=when)

    def _work(self, when):
        return GroupWork.objects.create(school=self.school, class_group=self.turma, subject=self.mat,
                                        title="Cartaz", description="x", created_by=self.prof,
                                        status=GroupWork.Status.PUBLISHED, deadline=when)

    def _exam(self, when):
        return Evaluation.objects.create(school=self.school, class_group=self.turma, subject=self.mat,
                                         title="Prova", date=when, status=Evaluation.Status.PUBLISHED)

    def test_prova_plus_trabalho_same_day_is_overloaded(self):
        day = self.today + timedelta(days=10)
        self._exam(day)
        self._work(day)
        days = workload.by_day(self.turma, self.today, self.today + timedelta(days=30))
        self.assertEqual(len(days), 1)
        self.assertEqual(days[0]["load"], 4)
        self.assertTrue(days[0]["overloaded"])
        self.assertEqual(days[0]["count"], 2)

    def test_three_activities_not_overloaded(self):
        day = self.today + timedelta(days=5)
        for _ in range(3):
            self._activity(day)
        days = workload.by_day(self.turma, self.today, self.today + timedelta(days=30))
        self.assertEqual(days[0]["load"], 3)
        self.assertFalse(days[0]["overloaded"])

    def test_drafts_and_out_of_window_excluded(self):
        day = self.today + timedelta(days=3)
        Activity.objects.create(school=self.school, class_group=self.turma, subject=self.mat, title="Rascunho",
                                description="x", created_by=self.prof, status=Activity.Status.DRAFT, deadline=day)
        self._exam(self.today + timedelta(days=200))  # fora da janela
        self.assertEqual(workload.by_day(self.turma, self.today, self.today + timedelta(days=30)), [])


class WorkloadViewTests(PedagogyBase):
    def test_access_and_render(self):
        url = reverse("pedagogy:deadline_load")
        day = timezone.localdate() + timedelta(days=7)
        Evaluation.objects.create(school=self.school, class_group=self.turma, subject=self.mat, title="Prova",
                                  date=day, status=Evaluation.Status.PUBLISHED)
        GroupWork.objects.create(school=self.school, class_group=self.turma, subject=self.mat, title="Cartaz",
                                 description="x", created_by=self.prof, status=GroupWork.Status.PUBLISHED,
                                 deadline=day)
        self.login("prof")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Concentração de prazos")
        # A família não tem essa tela.
        self.login("resp")
        self.assertIn(self.client.get(url).status_code, (302, 403))
