"""Registro de falhas técnicas (Prompt 2 §6): configuração, leitura e acesso."""

import tempfile
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Role, School, User

from ..views import _read_error_log

AMOSTRA = """2026-11-01 09:00:00,001 WARNING django.security.csrf: Forbidden (CSRF token missing.): /mensagens/
2026-11-02 10:15:30,123 ERROR django.request: Internal Server Error: /paineis/estudante/7/
Traceback (most recent call last):
  File "x.py", line 1, in <module>
ZeroDivisionError: division by zero
"""


class ErrorLogTests(TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="escola-logs-"))
        (self.dir / "erros.log").write_text(AMOSTRA, encoding="utf-8")
        school = School.objects.create(name="Escola", code="e")
        for name, role in (("adm", Role.ADMIN), ("dir", Role.DIRECAO), ("sec", Role.SECRETARIA)):
            User.objects.create_user(name, password="senha-forte-1", role=role, school=school)

    def test_parser_groups_traceback_newest_first(self):
        entries = _read_error_log(self.dir / "erros.log")
        self.assertEqual([e["level"] for e in entries], ["ERROR", "WARNING"])
        self.assertEqual(entries[0]["when"], "2026-11-02 10:15:30")
        self.assertIn("/paineis/estudante/7/", entries[0]["message"])
        self.assertIn("ZeroDivisionError", entries[0]["detail"])
        self.assertEqual(_read_error_log(self.dir / "nao-existe.log"), [])

    def test_only_admin_sees_the_page(self):
        with override_settings(LOG_DIR=self.dir):
            self.client.login(username="adm", password="senha-forte-1")
            resp = self.client.get(reverse("error_log"))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "ZeroDivisionError")
            self.assertEqual(resp.context["errors"], 1)
            for user in ("dir", "sec"):
                self.client.login(username=user, password="senha-forte-1")
                self.assertEqual(self.client.get(reverse("error_log")).status_code, 403, user)

    def test_server_errors_are_configured_to_be_recorded(self):
        loggers = settings.LOGGING["loggers"]
        self.assertEqual(loggers["django.request"]["level"], "ERROR")
        self.assertIn("arquivo", loggers["django.request"]["handlers"])
        self.assertEqual(loggers["django.security"]["level"], "WARNING")
