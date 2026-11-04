"""Retenção de dados (P9-32): relata sempre, apaga só dado operacional e só com --aplicar."""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.communication.models import Notification
from apps.core.models import AuditLog, Role, School, User


class RetentionTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        self.user = User.objects.create_user("resp", password="senha-forte-1", role=Role.RESPONSAVEL,
                                             school=self.school)
        old = timezone.now() - timedelta(days=400)
        self.old_read = Notification.objects.create(school=self.school, user=self.user, title="velho lido",
                                                    is_read=True)
        self.old_unread = Notification.objects.create(school=self.school, user=self.user, title="velho não lido")
        self.new_read = Notification.objects.create(school=self.school, user=self.user, title="novo lido",
                                                    is_read=True)
        Notification.objects.filter(pk__in=[self.old_read.pk, self.old_unread.pk]).update(created_at=old)

    def run_cmd(self, *args):
        out = StringIO()
        call_command("retencao", *args, stdout=out)
        return out.getvalue()

    def test_default_only_reports(self):
        out = self.run_cmd()
        self.assertIn("avisos lidos: 1", out)
        self.assertIn("Nada foi apagado", out)
        self.assertEqual(Notification.objects.count(), 3)

    def test_apply_deletes_only_old_read_notices_and_audits(self):
        self.run_cmd("--aplicar")
        self.assertEqual(set(Notification.objects.values_list("title", flat=True)), {"velho não lido", "novo lido"})
        self.assertTrue(AuditLog.objects.filter(target_type="Retenção", detail__contains="avisos lidos: 1").exists())

    def test_old_gate_records_go_but_the_attendance_stays(self):
        import datetime as dt

        from apps.academics.models import ClassGroup, SchoolYear
        from apps.gate.models import GateEvent
        from apps.pedagogy.models import AttendanceRecord
        from apps.registry.models import Student

        year = SchoolYear.objects.create(school=self.school, name="2023")
        cg = ClassGroup.objects.create(school=self.school, school_year=year, name="6º Ano A")
        st = Student.objects.create(school=self.school, first_name="Ana")
        old_day, new_day = dt.date.today() - dt.timedelta(days=800), dt.date.today()
        for day in (old_day, new_day):
            when = timezone.make_aware(dt.datetime.combine(day, dt.time(7, 50)))
            GateEvent.objects.create(school=self.school, student=st, class_group=cg, kind="entrada", method="qr",
                                     day=day, at=when, late=True, minutes_late=20)
        AttendanceRecord.objects.create(school=self.school, class_group=cg, student=st, date=old_day, status="atraso")
        self.assertIn("registros de portaria antigos: 1", self.run_cmd())
        self.run_cmd("--aplicar")
        self.assertEqual(list(GateEvent.objects.values_list("day", flat=True)), [new_day])
        self.assertTrue(AttendanceRecord.objects.filter(date=old_day, status="atraso").exists())  # registro escolar
