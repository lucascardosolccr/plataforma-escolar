from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone

from apps.analytics.views import _csv_safe
from apps.pedagogy.models import Activity

from .test_analytics import AnalyticsBase
from .. import services


class PeriodAndStatusRemediationTests(AnalyticsBase):
    def test_future_activity_is_not_counted_as_pending(self):
        Activity.objects.create(
            school=self.school,
            class_group=self.turma,
            subject=self.mat,
            title="Atividade agendada",
            status=Activity.Status.PUBLISHED,
            published_date=timezone.localdate() + timedelta(days=5),
        )
        stats = services.activity_stats(self.ana)
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["pending"], 0)

    def test_grade_evolution_respects_period(self):
        self.make_evaluation(self.ana, 8, date="2026-03-01")
        self.make_evaluation(self.ana, 9, date="2026-04-01")
        evolution = services.grade_evolution(
            self.ana,
            start=date(2026, 4, 1),
            end=date(2026, 4, 30),
        )
        self.assertEqual(len(evolution), 1)
        self.assertEqual(evolution[0]["value"], 9.0)


class CsvSafetyTests(AnalyticsBase):
    def test_csv_formula_prefixes_are_neutralized(self):
        for value in ("=2+2", "+cmd", "-1+1", "@SUM(A1)"):
            self.assertEqual(_csv_safe(value), "'" + value)
        self.assertEqual(_csv_safe("texto normal"), "texto normal")
        self.assertEqual(_csv_safe(10), 10)


class InstitutionalDashboardTests(AnalyticsBase):
    def test_dashboard_cards_receive_the_indicators(self):
        from apps.pedagogy.models import AttendanceRecord

        # Um presente e um ausente: frequência calculada de 50%.
        AttendanceRecord.objects.create(
            school=self.school, class_group=self.turma, student=self.ana,
            date=date(2026, 3, 2), status=AttendanceRecord.Status.PRESENT,
        )
        AttendanceRecord.objects.create(
            school=self.school, class_group=self.turma, student=self.ana,
            date=date(2026, 3, 3), status=AttendanceRecord.Status.ABSENT,
        )
        self.login("dir")
        resp = self.client.get(reverse("analytics:institutional_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total_students"], 2)
        self.assertEqual(resp.context["class_groups_count"], 2)
        self.assertEqual(resp.context["attendance_rate"], 50.0)


class InstitutionalNoDataTests(AnalyticsBase):
    def test_school_without_attendance_shows_no_data_not_zero(self):
        """Sem registro de frequência é "sem dado", não 0% (que pareceria uma
        escola inteira faltando)."""
        from apps.pedagogy.models import AttendanceRecord

        AttendanceRecord.objects.filter(school=self.school).delete()
        self.login("dir")
        resp = self.client.get(reverse("analytics:institutional_dashboard"))
        self.assertIsNone(resp.context["attendance_rate"])
        self.assertNotContains(resp, "0,0%")
