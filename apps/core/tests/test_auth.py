from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.core.models import AuditLog, Role, School
from apps.core.pagination import PAGE_SIZE

User = get_user_model()


class BaseAuthTest(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola Teste", code="teste")
        self.admin = User.objects.create_user(
            username="admin",
            password="senha-forte-1",
            role=Role.ADMIN,
            school=self.school,
        )
        self.admin.is_staff = True
        self.admin.save()
        self.professor = User.objects.create_user(
            username="prof",
            password="senha-forte-1",
            role=Role.PROFESSOR,
            school=self.school,
        )
        self.client = Client()


class LoginLogoutTests(BaseAuthTest):
    def test_login_success(self):
        ok = self.client.login(username="admin", password="senha-forte-1")
        self.assertTrue(ok)
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Escola Teste")

    def test_login_failure_redirects_and_logs_audit(self):
        resp = self.client.post(
            "/login/",
            {"username": "admin", "password": "errada"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            AuditLog.objects.filter(action="login_failed").exists(),
            "Falha de login deve ser registrada em auditoria",
        )

    def test_logout_requires_post(self):
        self.client.login(username="admin", password="senha-forte-1")
        resp = self.client.get("/logout/")
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(self.client.session and self.client.session.get("_auth_user_id"))

    def test_logout_generates_audit(self):
        self.client.login(username="admin", password="senha-forte-1")
        self.client.post("/logout/")
        self.assertTrue(AuditLog.objects.filter(user=self.admin, action="logout").exists())

    def test_anonymous_blocked_from_home(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp.url)


class PasswordChangeTests(BaseAuthTest):
    def test_password_change_flow(self):
        self.client.login(username="admin", password="senha-forte-1")
        resp = self.client.post(
            "/senha/trocar/",
            {"old_password": "senha-forte-1", "new_password1": "nova-senha-2", "new_password2": "nova-senha-2"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("nova-senha-2"))


class UserListPaginationTests(BaseAuthTest):
    def test_user_list_renders_paginator(self):
        self.client.login(username="admin", password="senha-forte-1")
        for i in range(PAGE_SIZE + 5):
            User.objects.create_user(
                username=f"usuario-{i:02d}",
                password="senha-forte-1",
                role=Role.SECRETARIA,
                school=self.school,
            )
        resp = self.client.get(reverse("user_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["page"].has_other_pages())
        self.assertContains(resp, "pagina=")
        self.assertContains(resp, "Anterior")
        self.assertContains(resp, "Próxima")