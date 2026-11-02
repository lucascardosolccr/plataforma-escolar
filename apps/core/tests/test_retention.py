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
