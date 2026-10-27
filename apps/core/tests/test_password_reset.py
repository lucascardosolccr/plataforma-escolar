"""Senha temporária gerada pela escola e troca obrigatória.

A plataforma não envia e-mail (custo zero), então não existe recuperação por
link. Quem esquece a senha pede à secretaria ou à administração.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.models import AuditLog, Role, School
from apps.core.passwords import can_reset_password, generate_temp_password

User = get_user_model()
PW = "senha-forte-1"


class PasswordResetBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola A", code="a")
        self.outra = School.objects.create(name="Escola B", code="b")

        def mk(username, role, school=None):
            return User.objects.create_user(
                username=username, password=PW, role=role,
                school=school or self.school,
            )

        self.admin = mk("adm", Role.ADMIN)
        self.sec = mk("sec", Role.SECRETARIA)
        self.coord = mk("coord", Role.COORDENACAO)
        self.prof = mk("prof", Role.PROFESSOR)
        self.resp = mk("resp", Role.RESPONSAVEL)
        self.resp_outra = mk("resp_b", Role.RESPONSAVEL, self.outra)

    def login(self, username):
        self.client.login(username=username, password=PW)

    def url(self, target):
        return reverse("password_reset_user", args=[target.pk])


class TempPasswordTests(TestCase):
    def test_generated_password_is_long_and_unambiguous(self):
        senha = generate_temp_password()
        self.assertGreaterEqual(len(senha), 12)
        # Caracteres confundíveis ficam de fora: a senha é lida de um papel.
        for c in "O0ol1I":
            self.assertNotIn(c, senha)

    def test_generated_passwords_differ(self):
        senhas = {generate_temp_password() for _ in range(50)}
        self.assertEqual(len(senhas), 50)


class PermissionTests(PasswordResetBase):
    def test_admin_can_reset_anyone_in_own_school(self):
        for alvo in (self.sec, self.coord, self.prof, self.resp):
            self.assertTrue(can_reset_password(self.admin, alvo))

    def test_secretaria_can_reset_only_guardians(self):
        self.assertTrue(can_reset_password(self.sec, self.resp))
        for alvo in (self.coord, self.prof, self.admin):
            self.assertFalse(
                can_reset_password(self.sec, alvo),
                f"secretaria não deveria redefinir {alvo.role}",
            )

    def test_nobody_resets_across_schools(self):
        self.assertFalse(can_reset_password(self.admin, self.resp_outra))
        self.assertFalse(can_reset_password(self.sec, self.resp_outra))

    def test_nobody_resets_own_password_through_this_route(self):
        self.assertFalse(can_reset_password(self.admin, self.admin))

    def test_teacher_and_guardian_cannot_reset(self):
        self.assertFalse(can_reset_password(self.prof, self.resp))
        self.assertFalse(can_reset_password(self.resp, self.prof))


class ResetViewTests(PasswordResetBase):
    def test_requires_post(self):
        self.login("adm")
        self.assertEqual(self.client.get(self.url(self.resp)).status_code, 405)

    def test_admin_reset_changes_password_and_shows_it_once(self):
        self.login("adm")
        resp = self.client.post(self.url(self.resp))
        self.assertEqual(resp.status_code, 200)
        senha = resp.context["temp_password"]
        self.assertContains(resp, senha)

        self.resp.refresh_from_db()
        self.assertTrue(self.resp.must_change_password)
        self.assertFalse(self.resp.check_password(PW), "senha antiga ainda vale")
        self.assertTrue(self.resp.check_password(senha))

    def test_secretaria_can_reset_guardian(self):
        self.login("sec")
        self.assertEqual(self.client.post(self.url(self.resp)).status_code, 200)

    def test_secretaria_cannot_reset_teacher(self):
        self.login("sec")
        self.assertEqual(self.client.post(self.url(self.prof)).status_code, 403)
        self.prof.refresh_from_db()
        self.assertTrue(self.prof.check_password(PW), "a senha não deveria mudar")

    def test_teacher_cannot_reset_anyone(self):
        self.login("prof")
        self.assertEqual(self.client.post(self.url(self.resp)).status_code, 403)

    def test_cross_school_reset_is_blocked(self):
        self.login("adm")
        self.assertEqual(self.client.post(self.url(self.resp_outra)).status_code, 403)

    def test_reset_is_audited(self):
        self.login("adm")
        self.client.post(self.url(self.resp))
        self.assertTrue(
            AuditLog.objects.filter(
                user=self.admin, detail__contains="Redefiniu a senha de resp"
            ).exists()
        )


class ForcePasswordChangeTests(PasswordResetBase):
    def test_user_with_temp_password_is_sent_to_password_change(self):
        self.resp.must_change_password = True
        self.resp.save(update_fields=["must_change_password"])
        self.login("resp")
        resp = self.client.get(reverse("home"))
        self.assertRedirects(resp, reverse("password_change"))

    def test_password_change_page_itself_is_reachable(self):
        self.resp.must_change_password = True
        self.resp.save(update_fields=["must_change_password"])
        self.login("resp")
        self.assertEqual(
            self.client.get(reverse("password_change")).status_code, 200
        )

    def test_changing_password_clears_the_flag_and_frees_navigation(self):
        self.resp.must_change_password = True
        self.resp.save(update_fields=["must_change_password"])
        self.login("resp")
        nova = "outra-senha-forte-9"
        self.client.post(
            reverse("password_change"),
            {"old_password": PW, "new_password1": nova, "new_password2": nova},
        )
        self.resp.refresh_from_db()
        self.assertFalse(self.resp.must_change_password)
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_normal_user_is_not_redirected(self):
        self.login("resp")
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_new_professional_account_requires_change(self):
        self.login("adm")
        self.client.post(
            reverse("user_create"),
            {
                "username": "novoprof",
                "first_name": "Novo",
                "last_name": "Professor",
                "email": "novo@escola.test",
                "role": Role.PROFESSOR.value,
                "school": self.school.pk,
                "password1": "temporaria-forte-7",
                "password2": "temporaria-forte-7",
            },
        )
        novo = User.objects.get(username="novoprof")
        self.assertTrue(novo.must_change_password)
