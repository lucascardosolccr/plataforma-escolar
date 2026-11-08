"""Painel interativo (estilo BI): dados com o mesmo acesso, as mesmas restrições e os mesmos números dos painéis.

A conta feita no navegador (static/js/bi-explorer.js) foi conferida contra bi.py na cópia de teste do banco
(18 estudantes, todas as disciplinas, 08/11/2026); aqui ficam as garantias do lado do servidor.
"""

from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.pedagogy.models import AttendanceRecord, Evaluation, Grade

from .test_bi_access import PW, Q, BIAccessBase


class ExplorerAccessTests(BIAccessBase):
    def test_student_data_follows_the_student_panel_access(self):
        allowed = ["admin", "direcao", "coordenacao", "secretaria", "prof", "resp", "aluno"]
        self.matrix(reverse("analytics:student_data", args=[self.ana.pk]) + Q, allowed)

    def test_class_data_follows_the_class_panel_access(self):
        allowed = ["admin", "direcao", "coordenacao", "secretaria", "prof"]
        self.matrix(reverse("analytics:class_data", args=[self.t1.pk]) + Q, allowed)

    def test_data_is_never_cached_by_shared_caches(self):
        self.client.login(username="direcao", password=PW)
        resp = self.client.get(reverse("analytics:class_data", args=[self.t1.pk]) + Q)
        self.assertEqual(resp["Cache-Control"], "private, no-store")

    def test_pages_carry_the_interactive_panel_and_keep_the_detailed_report(self):
        self.client.login(username="direcao", password=PW)
        for url, data_url in (
            (reverse("analytics:class_dashboard", args=[self.t1.pk]), reverse("analytics:class_data", args=[self.t1.pk])),
            (reverse("analytics:student_dashboard", args=[self.ana.pk]), reverse("analytics:student_data", args=[self.ana.pk])),
        ):
            page = self.client.get(url + Q)
            self.assertContains(page, f'data-src="{data_url}?periodo=personalizado')
            self.assertContains(page, "js/bi-explorer.js")
            self.assertContains(page, 'id="relatorio-detalhado"')


class ExplorerContentTests(BIAccessBase):
    def setUp(self):
        super().setUp()
        ev_por = Evaluation.objects.create(school=self.school, subject=self.por, class_group=self.t1, title="P2",
                                           date=date(2026, 4, 2), status=Evaluation.Status.PUBLISHED,
                                           created_by=self.prof)
        Grade.objects.create(school=self.school, evaluation=ev_por, student=self.ana, value=Decimal("4.5"))
        draft = Evaluation.objects.create(school=self.school, subject=self.mat, class_group=self.t1, title="Rascunho",
                                          date=date(2026, 4, 5), status=Evaluation.Status.DRAFT, created_by=self.prof)
        Grade.objects.create(school=self.school, evaluation=draft, student=self.ana, value=Decimal("1"))
        for d, st in ((date(2026, 3, 2), "presente"), (date(2026, 3, 3), "falta"), (date(2026, 3, 4), "atraso")):
            AttendanceRecord.objects.create(school=self.school, class_group=self.t1, student=self.ana, date=d, status=st)

    def get(self, username, url):
        self.client.logout()
        self.client.login(username=username, password=PW)
        return self.client.get(url + Q).json()

    def test_teacher_sees_only_the_subjects_he_teaches(self):
        data = self.get("prof", reverse("analytics:class_data", args=[self.t1.pk]))
        self.assertEqual([s["name"] for s in data["subjects"]], ["Matemática"])
        self.assertEqual([e[3] for e in data["evaluations"]], ["P1"])
        student = self.get("prof", reverse("analytics:student_data", args=[self.ana.pk]))
        self.assertEqual({g[1] for g in student["grades"]}, {self.mat.pk})

    def test_only_published_grades_and_compact_attendance(self):
        data = self.get("direcao", reverse("analytics:student_data", args=[self.ana.pk]))
        self.assertEqual(sorted(g[4] for g in data["grades"]), ["P1", "P2"])  # o rascunho não aparece
        self.assertEqual([a[1] for a in data["attendance"]], ["P", "F", "A"])
        self.assertEqual(data["meta"]["min_attendance"], 75.0)
        self.assertEqual(data["meta"]["rules"][str(self.mat.pk)], {"formula": "aritmetica", "passing": 6.0})

    def test_class_mean_only_for_the_team_and_with_five_or_more_grades(self):
        team = self.get("direcao", reverse("analytics:student_data", args=[self.ana.pk]))
        self.assertTrue(all(g[6] is None for g in team["grades"]))  # 1 nota por avaliação: grupo pequeno
        family = self.get("resp", reverse("analytics:student_data", args=[self.ana.pk]))
        self.assertFalse(family["meta"]["class_comparison"])

    def test_class_payload_links_students_only_when_the_viewer_can_open_them(self):
        data = self.get("prof", reverse("analytics:class_data", args=[self.t1.pk]))
        self.assertEqual(data["students"][0]["url"], reverse("analytics:student_dashboard", args=[self.ana.pk]))
        self.assertEqual(data["grades"], [[0, 0, 7.0]])
