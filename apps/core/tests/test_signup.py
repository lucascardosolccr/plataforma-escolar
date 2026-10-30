from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.models import AuditLog, Role, School

User = get_user_model()


class PublicSignupTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola Teste", code="escola-teste")

    def test_signup_creates_responsavel_only(self):
        resp = self.client.post(
            reverse("signup"),
            {
                "school_code": "escola-teste",
                "username": "pai123",
                "first_name": "João",
                "last_name": "Silva",
                "email": "joao@test.com",
                "password1": "senha-forte-1",
                "password2": "senha-forte-1",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        user = User.objects.get(username="pai123")
        self.assertEqual(user.role, Role.RESPONSAVEL)
        self.assertEqual(user.school, self.school)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.guardian_profile)

    def test_signup_cannot_elevate_role_even_with_crafted_post(self):
        resp = self.client.post(
            reverse("signup"),
            {
                "school_code": "escola-teste",
                "username": "atacante",
                "first_name": "X",
                "email": "x@test.com",
                "password1": "senha-forte-1",
                "password2": "senha-forte-1",
                "role": Role.ADMIN,
                "is_staff": "on",
                "is_superuser": "on",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        user = User.objects.get(username="atacante")
        # Campos de privilégio são ignorados no servidor — perfil e flags vêm
        # fixos do formulário de cadastro público.
        self.assertEqual(user.role, Role.RESPONSAVEL)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_signup_wrong_school_code_rejected(self):
        resp = self.client.post(
            reverse("signup"),
            {
                "school_code": "nao-existe",
                "username": "pai2",
                "first_name": "A",
                "email": "a@test.com",
                "password1": "senha-forte-1",
                "password2": "senha-forte-1",
            },
        )
        self.assertContains(resp, "Código de escola não encontrado")
        self.assertFalse(User.objects.filter(username="pai2").exists())

    def test_signup_new_user_can_login(self):
        self.client.post(
            reverse("signup"),
            {
                "school_code": "escola-teste",
                "username": "mae123",
                "first_name": "Maria",
                "email": "maria@test.com",
                "password1": "senha-forte-1",
                "password2": "senha-forte-1",
            },
        )
        self.assertTrue(self.client.login(username="mae123", password="senha-forte-1"))

    def test_signup_recorded_in_audit(self):
        self.client.post(
            reverse("signup"),
            {
                "school_code": "escola-teste",
                "username": "avo123",
                "first_name": "Antonio",
                "email": "a2@test.com",
                "password1": "senha-forte-1",
                "password2": "senha-forte-1",
            },
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="create", target_type="User", detail__contains="Cadastro público"
            ).exists()
        )

class SignupRateLimitTests(TestCase):
    def setUp(self):
        School.objects.create(name="Escola Teste", code="escola-teste")

    def signup(self, n, ip):
        return self.client.post(reverse("signup"), {
            "school_code": "escola-teste", "username": f"resp{n}", "first_name": "R", "email": f"r{n}@t.com",
            "password1": "senha-forte-1", "password2": "senha-forte-1",
        }, REMOTE_ADDR=ip)

    def test_sixth_signup_from_same_address_in_an_hour_is_refused(self):
        for n in range(5):
            self.assertEqual(self.signup(n, "10.1.1.1").status_code, 302)
        resp = self.signup(5, "10.1.1.1")
        self.assertContains(resp, "Muitos cadastros")
        self.assertFalse(User.objects.filter(username="resp5").exists())
        # Outro endereço continua podendo se cadastrar.
        self.assertEqual(self.signup(6, "10.1.1.2").status_code, 302)
