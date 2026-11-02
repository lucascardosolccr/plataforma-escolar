"""Utilização dos módulos no painel institucional (Prompt 9 §6.1)."""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditLog
from apps.pedagogy.models import Activity, AttendanceRecord

from .. import bi
from .test_analytics import AnalyticsBase


class ModuleUsageTests(AnalyticsBase):
    def test_counts_come_from_the_tables(self):
        today = timezone.localdate()
        for title in ("Lista 1", "Lista 2"):
            Activity.objects.create(school=self.school, class_group=self.turma, subject=self.mat,
                                    title=title, created_by=self.prof)
        Activity.objects.create(school=self.school_b, class_group=self.turma, subject=self.mat,
                                title="Outra escola", created_by=self.prof)
        # Dois estudantes na mesma chamada contam um dia de chamada.
        for student in (self.ana, self.bea):
            AttendanceRecord.objects.create(school=self.school, class_group=self.turma,
                                            student=student, date=today)
        for _ in range(3):  # três logins do mesmo professor: uma conta
            AuditLog.objects.create(user=self.prof, school=self.school, action="login")
        AuditLog.objects.create(user=self.resp, school=self.school, action="login")

        usage = bi.module_usage(self.school, bi.resolve_period({"periodo": "30d"}, self.school))
        counts = {m["label"]: m["count"] for m in usage["modules"]}
        self.assertEqual(counts["Atividades de casa criadas"], 2)
        self.assertEqual(counts["Dias de chamada (turma e data)"], 1)
        self.assertEqual(counts["Ocorrências registradas"], 0)
        self.assertEqual({l["role"]: l["users"] for l in usage["logins"]},
                         {"Professor": 1, "Responsável": 1})

    def test_period_filter_applies(self):
        act = Activity.objects.create(school=self.school, class_group=self.turma, subject=self.mat,
                                      title="Antiga", created_by=self.prof)
        Activity.objects.filter(pk=act.pk).update(created_at=timezone.now() - timedelta(days=60))
        usage = bi.module_usage(self.school, bi.resolve_period({"periodo": "30d"}, self.school))
        self.assertEqual(usage["modules"][0]["count"], 0)

    def test_section_on_institutional_dashboard(self):
        self.client.login(username="dir", password="senha-forte-1")
        resp = self.client.get(reverse("analytics:institutional_dashboard"))
        self.assertContains(resp, "Utilização da plataforma")
        self.assertNotContains(resp, "Metas institucionais não são cadastradas")
        self.client.login(username="prof", password="senha-forte-1")
        self.assertEqual(self.client.get(reverse("analytics:institutional_dashboard")).status_code, 403)
