from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from apps.core.models import AuditLog, Role, School, User

User = get_user_model()


class RbacTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola A", code="a")
        self.school_b = School.objects.create(name="Escola B", code="b")
        self.admin = User.objects.create_user(
            username="admin", password="senha-forte-1", role=Role.ADMIN, school=self.school
        )
        self.professor = User.objects.create_user(
            username="prof", password="senha-forte-1", role=Role.PROFESSOR, school=self.school
        )
        self.responsavel = User.objects.create_user(
            username="resp", password="senha-forte-1", role=Role.RESPONSAVEL, school=self.school
        )
        self.client = Client()

    def test_admin_only_user_management(self):
        for username in ("prof", "resp"):
            self.client.login(username=username, password="senha-forte-1")
            self.assertEqual(self.client.get("/usuarios/").status_code, 403)

        self.client.login(username="admin", password="senha-forte-1")
        self.assertEqual(self.client.get("/usuarios/").status_code, 200)

    def test_admin_only_user_creation(self):
        self.client.login(username="prof", password="senha-forte-1")
        resp = self.client.post(
            "/usuarios/novo/",
            {
                "username": "invasor",
                "first_name": "X",
                "last_name": "Y",
                "role": Role.DIRECAO,
                "school": self.school.pk,
                "password1": "qualquer-1",
                "password2": "qualquer-1",
            },
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(User.objects.filter(username="invasor").exists())

    def test_anonymous_cannot_create_professional_account(self):
        resp = self.client.post(
            "/usuarios/novo/",
            {
                "username": "invasor",
                "role": Role.DIRECAO,
                "school": self.school.pk,
                "password1": "qualquer-1",
                "password2": "qualquer-1",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp.url)
        self.assertFalse(User.objects.filter(username="invasor").exists())

    def test_admin_creates_professional_without_superuser_privileges(self):
        self.client.login(username="admin", password="senha-forte-1")
        resp = self.client.post(
            "/usuarios/novo/",
            {
                "username": "novaprof",
                "first_name": "Nova",
                "last_name": "Professora",
                "email": "novaprof@escola.test",
                "role": Role.PROFESSOR,
                "school": self.school.pk,
                "password1": "temp-1234",
                "password2": "temp-1234",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        nova = User.objects.get(username="novaprof")
        self.assertEqual(nova.role, Role.PROFESSOR)
        self.assertFalse(nova.is_superuser, "Contas criadas não podem ter privilégios de superusuário")
        self.assertFalse(nova.is_staff, "Contas criadas não podem ter privilégios administrativos")
        self.assertTrue(
            AuditLog.objects.filter(user=self.admin, action="create", target_type="User").exists()
        )

    def test_user_cannot_elevate_own_role(self):
        """Um usuário não consegue elevar o próprio privilégio."""
        self.client.login(username="prof", password="senha-forte-1")
        resp = self.client.post("/usuarios/novo/", {"role": Role.ADMIN})
        self.assertEqual(resp.status_code, 403)
        self.professor.refresh_from_db()
        self.assertEqual(self.professor.role, Role.PROFESSOR)

    def test_admin_cannot_assign_account_to_other_school(self):
        """Isolamento entre escolas: o administrador só cria contas na própria escola."""
        self.client.login(username="admin", password="senha-forte-1")
        resp = self.client.post(
            "/usuarios/novo/",
            {
                "username": "estranho",
                "first_name": "E",
                "last_name": "S",
                "role": Role.PROFESSOR,
                "school": self.school_b.pk,
                "password1": "temp-1234",
                "password2": "temp-1234",
            },
        )
        self.assertFalse(User.objects.filter(username="estranho").exists())

    def test_detail_is_isolated_between_schools(self):
        outros_admin = User.objects.create_user(
            username="admin_b", password="senha-forte-1", role=Role.ADMIN, school=self.school_b
        )
        self.client.login(username="admin_b", password="senha-forte-1")
        resp = self.client.get(f"/usuarios/{self.admin.pk}/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/usuarios/", resp.url)