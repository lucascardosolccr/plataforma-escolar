"""Metas da escola: cadastro pela direção, progresso calculado com as fórmulas dos painéis."""

from datetime import timedelta

from django.urls import reverse

from apps.analytics import goals
from apps.analytics.models import SchoolGoal
from apps.cognitio.evidence import rebuild_class
from apps.cognitio.models import SkillObservation
from apps.cognitio.tests.test_evidence import Base
from apps.core.models import AuditLog
from apps.pedagogy.models import AttendanceRecord


class GoalTests(Base):
    def goal(self, **kw):
        defaults = dict(school=self.school, indicator="frequencia", target=90,
                        starts_on=self.today - timedelta(days=10), deadline=self.today + timedelta(days=30))
        defaults.update(kw)
        return SchoolGoal.objects.create(**defaults)

    def test_direction_creates_and_coordination_restricted_cannot_see(self):
        url = reverse("analytics:goal_create")
        for user in (self.prof, self.sec, self.coord):  # coord deste teste tem designação restrita a uma turma
            self.login(user)
            self.assertEqual(self.client.get(reverse("analytics:goals")).status_code, 403, user.username)
            self.assertEqual(self.client.get(url).status_code, 403, user.username)
        self.login(self.dir)
        r = self.client.post(url, {"indicator": "frequencia", "class_group": "", "target": "95",
                                   "starts_on": self.today.isoformat(),
                                   "deadline": (self.today - timedelta(days=1)).isoformat()})
        self.assertContains(r, "O prazo precisa ser depois do início.")
        r = self.client.post(url, {"indicator": "frequencia", "class_group": "", "target": "120",
                                   "starts_on": self.today.isoformat(),
                                   "deadline": (self.today + timedelta(days=60)).isoformat()})
        self.assertContains(r, "Use um valor entre 0 e 100.")
        r = self.client.post(url, {"indicator": "frequencia", "class_group": "", "target": "92",
                                   "starts_on": self.today.isoformat(),
                                   "deadline": (self.today + timedelta(days=60)).isoformat(),
                                   "notes": "Busca ativa das famílias"})
        self.assertRedirects(r, reverse("analytics:goals"))
        g = SchoolGoal.objects.get()
        self.assertEqual((g.school, g.created_by, g.label), (self.school, self.dir, "Frequência média (%)"))
        self.assertTrue(AuditLog.objects.filter(detail__startswith="Cadastrou a meta").exists())
        r = self.client.get(reverse("analytics:goals"))
        self.assertContains(r, "Busca ativa das famílias")
        self.assertContains(r, "Sem dados ainda")  # sem chamada no período: nunca zero
        self.client.post(reverse("analytics:goal_edit", args=[g.pk]), {"acao": "desativar"})
        g.refresh_from_db()
        self.assertFalse(g.active)

    def test_progress_uses_the_panel_formulas(self):
        g = self.goal(target=90)
        day = self.today - timedelta(days=2)
        for st, status in ((self.ana, "presente"), (self.bia, "presente"), (self.caio, "falta")):
            AttendanceRecord.objects.create(school=self.school, class_group=self.cg, student=st, date=day,
                                            status=status, recorded_by=self.prof)
        p = goals.progress(g)
        self.assertEqual((p["value"], p["status"], p["gap"]), (66.7, "abaixo", 23.3))
        g.target = 60
        self.assertEqual(goals.progress(g)["status"], "atingida")
        g.deadline = self.today - timedelta(days=1)  # prazo vencido e abaixo do alvo
        g.target = 99
        self.assertEqual(goals.progress(g)["status"], "nao_atingida")
        # turma com menos de 5 estudantes: sem valor (proteção de grupos pequenos)
        self.assertIsNone(goals.progress(self.goal(class_group=self.cg))["value"])

    def test_skills_indicator_from_cognitio(self):
        for item, lvl in ((self.h1, 5), (self.h2, 1)):
            for _ in range(2):
                SkillObservation.objects.create(school=self.school, student=self.ana, item=item, class_group=self.cg,
                                                subject=self.mat, teacher=self.prof, level=lvl, context="Sala",
                                                observed_on=self.today - timedelta(days=1))
        rebuild_class(self.cg)
        p = goals.progress(self.goal(indicator="habilidades", target=40))
        self.assertEqual((p["value"], p["status"]), (50.0, "atingida"))
