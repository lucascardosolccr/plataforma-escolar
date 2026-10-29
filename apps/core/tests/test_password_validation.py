from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Role, School

User = get_user_model()


class PasswordValidationTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola Teste", code="escola-teste")
        self.admin = User.objects.create_user(
            username="admin",
            password="senha-forte-1",
            role=Role.ADMIN,
            school=self.school,
        )

    def test_public_signup_rejects_weak_password(self):
        resp = self.client.post(
            reverse("signup"),
            {
                "school_code": "escola-teste",
                "username": "senha-fraca",
                "first_name": "Ana",
                "email": "ana@escola.test",
                "password1": "12345678",
                "password2": "12345678",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="senha-fraca").exists())

    def test_professional_account_rejects_weak_password(self):
        self.client.login(username="admin", password="senha-forte-1")
        resp = self.client.post(
            reverse("user_create"),
            {
                "username": "senha-fraca",
                "first_name": "Ana",
                "last_name": "Silva",
                "email": "ana@escola.test",
                "role": Role.PROFESSOR,
                "school": self.school.pk,
                "password1": "12345678",
                "password2": "12345678",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="senha-fraca").exists())
