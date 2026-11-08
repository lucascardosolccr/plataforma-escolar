"""Escolas cadastradas pelo administrador da plataforma e equipe que se cadastra com código de convite."""

import datetime as dt
import random

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification
from apps.communication.tests.test_communication import CommunicationBase
from apps.core import invites
from apps.core.models import AuditLog, InviteCode, InviteSignup, Role, School, User

PASSWORD = "Senha-Forte-2026!x"


def signup_data(code, username="nova.pessoa", **extra):
    return {"code": code, "first_name": "Nova", "last_name": "Pessoa", "email": "nova@escola.example",
            "phone": "", "username": username, "password1": PASSWORD, "password2": PASSWORD, **extra}


class CodeTests(SimpleTestCase):
    def test_check_character_catches_typos_and_codes_are_normalized(self):
        rnd = random.Random(7)
        for _ in range(300):
            body = "".join(rnd.choice(invites.ALPHABET) for _ in range(11))
            code = body + invites._check_char(body)
            self.assertTrue(invites.valid_shape(code))
            i = rnd.randrange(11)
            wrong = rnd.choice([c for c in invites.ALPHABET if c != code[i]])
            self.assertFalse(invites.valid_shape(code[:i] + wrong + code[i + 1:]))
        self.assertEqual(invites.normalize(" k7m2-q9xp-4tra "), "K7M2Q9XP4TRA")
        self.assertEqual(invites.normalize("O1IL"), "0111")


class InviteBase(CommunicationBase):
    def setUp(self):
        super().setUp()
        self.root = User.objects.create_user(username="raiz", password=PASSWORD, role=Role.ADMIN.value,
                                             is_superuser=True, is_staff=True)

    def signup(self, code, **extra):
        self.client.logout()
        return self.client.post(reverse("invite_signup"), signup_data(code, **extra))


class PlatformAdminTests(InviteBase):
    def test_platform_admin_registers_a_school_and_gets_the_direction_code(self):
        self.client.force_login(self.root)
        page = self.client.post(reverse("school_create"), {"name": "EMEF Nova Esperança", "code": "EMEF Nova",
                                                           "inep": "1234-5678", "city": "Brasília", "uf": "df"},
                                follow=True)
        school = School.objects.get(code="emef-nova")
        self.assertEqual((school.inep, school.uf), ("12345678", "DF"))
        invite = InviteCode.objects.get(school=school)
        self.assertEqual((invite.role, invite.max_uses, invite.requires_approval), (Role.DIRECAO.value, 1, False))
        self.assertContains(page, invite.display_code)
        self.assertTrue(AuditLog.objects.filter(detail__startswith="Cadastrou a escola EMEF Nova").exists())

    def test_only_the_platform_admin_lists_and_creates_schools(self):
        for user in (self.admin, self.direc, self.sec, self.prof):  # admin da escola não é da plataforma
            self.client.force_login(user)
            for url in (reverse("school_list"), reverse("school_create")):
                self.assertEqual(self.client.get(url).status_code, 403, (user.username, url))
        self.client.force_login(self.root)
        self.assertContains(self.client.get(reverse("school_list")), "Escola B")

    def test_platform_admin_can_work_in_any_school(self):
        self.client.force_login(self.root)
        self.client.post(reverse("school_switch", args=[self.school_b.pk]))
        self.root.refresh_from_db()
        self.assertEqual(self.root.school, self.school_b)


class InviteSignupTests(InviteBase):
    def test_direction_code_creates_one_active_account_linked_to_the_school(self):
        invite = invites.create_invite(self.school_b, Role.DIRECAO.value, self.root)
        page = self.signup(invite.display_code.lower())
        self.assertContains(page, "Conta criada")
        user = User.objects.get(username="nova.pessoa")
        self.assertEqual((user.school, user.role, user.is_active, user.must_change_password),
                         (self.school_b, Role.DIRECAO.value, True, False))
        self.assertTrue(self.client.login(username="nova.pessoa", password=PASSWORD))
        again = self.signup(invite.code, username="outra.pessoa")
        self.assertContains(again, "número máximo de vezes")
        self.assertFalse(User.objects.filter(username="outra.pessoa").exists())

    def test_role_and_school_come_only_from_the_code(self):
        invite = invites.create_invite(self.school, Role.PROFESSOR.value, self.direc)
        self.signup(invite.code, role=Role.DIRECAO.value, school=self.school_b.pk)
        user = User.objects.get(username="nova.pessoa")
        self.assertEqual((user.role, user.school), (Role.PROFESSOR.value, self.school))

    def test_link_with_the_code_shows_school_and_role_before_signing_up(self):
        invite = invites.create_invite(self.school, Role.PROFESSOR.value, self.direc)
        page = self.client.get(reverse("invite_signup") + f"?codigo={invite.code}")
        self.assertContains(page, "Convite para <strong>Professor</strong> na escola <strong>Escola A</strong>")

    def test_secretaria_needs_approval_and_login_says_so_only_with_the_right_password(self):
        invite = invites.create_invite(self.school, Role.SECRETARIA.value, self.direc)
        self.assertContains(self.signup(invite.code), "aguarda a aprovação da direção")
        user = User.objects.get(username="nova.pessoa")
        self.assertFalse(user.is_active)
        self.assertTrue(Notification.objects.filter(user=self.direc, title__contains="aguardando aprovação").exists())
        right = self.client.post(reverse("login"), {"username": "nova.pessoa", "password": PASSWORD})
        self.assertContains(right, "ainda aguarda a aprovação")
        wrong = self.client.post(reverse("login"), {"username": "nova.pessoa", "password": "outra-senha-qualquer"})
        self.assertNotContains(wrong, "aprovação")
        self.client.force_login(self.direc)
        self.assertContains(self.client.get(reverse("pending_center")), "Cadastros da equipe aguardando aprovação")
        signup = InviteSignup.objects.get()
        self.client.post(reverse("signup_decide", args=[signup.pk]), {"decisao": "aprovar"})
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(self.client.login(username="nova.pessoa", password=PASSWORD))

    def test_rejected_account_is_deleted_and_frees_the_slot(self):
        invite = invites.create_invite(self.school, Role.SECRETARIA.value, self.direc, max_uses=1)
        self.signup(invite.code)
        signup = InviteSignup.objects.get()
        self.client.force_login(self.direc)
        self.client.post(reverse("signup_decide", args=[signup.pk]), {"decisao": "recusar"})
        self.assertFalse(User.objects.filter(username="nova.pessoa").exists())
        signup.refresh_from_db()
        self.assertEqual((signup.status, signup.name), (InviteSignup.Status.REJECTED, "Nova Pessoa"))
        self.assertContains(self.signup(invite.code, username="segunda.tentativa"), "aguarda a aprovação")

    def test_expired_revoked_mistyped_and_unknown_codes_are_refused(self):
        expired = invites.create_invite(self.school, Role.PROFESSOR.value, self.direc)
        InviteCode.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - dt.timedelta(minutes=1))
        revoked = invites.create_invite(self.school, Role.PROFESSOR.value, self.direc)
        invites.revoke(revoked, self.direc)
        typo = revoked.code[:-1] + ("0" if revoked.code[-1] != "0" else "1")
        unknown = "0" * 11 + invites._check_char("0" * 11)
        cases = {expired.code: "venceu", revoked.code: "cancelado", typo: "confira os 12 caracteres",
                 unknown: "não encontrado"}
        for code, message in cases.items():
            self.assertContains(self.signup(code), message, msg_prefix=code)
        self.assertFalse(User.objects.filter(username="nova.pessoa").exists())

    def test_repeated_wrong_codes_from_the_same_network_are_blocked(self):
        for _ in range(invites.FAILED_LIMIT_PER_HOUR):
            self.signup("0000-0000-0000")
        invite = invites.create_invite(self.school, Role.PROFESSOR.value, self.direc)
        self.assertContains(self.signup(invite.code), "Muitas tentativas")
        self.assertFalse(User.objects.filter(username="nova.pessoa").exists())


class SchoolTeamTests(InviteBase):
    def test_direction_invites_its_own_team_but_not_another_direction(self):
        self.client.force_login(self.direc)
        url = reverse("invite_create", args=[self.school.pk])
        self.client.post(url, {"role": Role.PROFESSOR.value, "note": "Fundamental II", "approval": "padrao"})
        invite = InviteCode.objects.get()
        self.assertEqual((invite.role, invite.max_uses, invite.requires_approval), (Role.PROFESSOR.value, 60, False))
        self.client.post(url, {"role": Role.DIRECAO.value, "approval": "padrao"})
        self.assertEqual(InviteCode.objects.count(), 1)
        page = self.client.get(reverse("school_team", args=[self.school.pk]))
        self.assertContains(page, invite.display_code)
        self.assertContains(page, f"?codigo={invite.code}")

    def test_other_schools_and_other_roles_cannot_see_or_use_the_team_page(self):
        invite = invites.create_invite(self.school, Role.PROFESSOR.value, self.direc)
        signup_target = invites.create_invite(self.school, Role.SECRETARIA.value, self.direc)
        self.signup(signup_target.code)
        pending = InviteSignup.objects.get()
        for user in (self.prof, self.sec, self.coord, self.resp):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("school_team", args=[self.school.pk])).status_code, 403)
            self.assertEqual(self.client.post(reverse("invite_revoke", args=[invite.pk])).status_code, 403)
            self.assertEqual(self.client.post(reverse("signup_decide", args=[pending.pk]),
                                              {"decisao": "aprovar"}).status_code, 403)
        self.client.force_login(self.direc)
        self.assertEqual(self.client.get(reverse("school_team", args=[self.school_b.pk])).status_code, 403)
        pending.refresh_from_db()
        self.assertEqual(pending.status, InviteSignup.Status.PENDING)

    def test_revoked_code_stops_new_signups_but_keeps_accounts(self):
        invite = invites.create_invite(self.school, Role.PROFESSOR.value, self.direc)
        self.signup(invite.code)
        self.client.force_login(self.direc)
        self.client.post(reverse("invite_revoke", args=[invite.pk]))
        self.assertContains(self.signup(invite.code, username="depois"), "cancelado")
        self.assertTrue(User.objects.get(username="nova.pessoa").is_active)

    def test_school_admin_invites_any_role_of_its_own_school(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("invite_create", args=[self.school.pk]),
                         {"role": Role.DIRECAO.value, "approval": "sim", "max_uses": 2, "days": 3})
        invite = InviteCode.objects.get()
        self.assertEqual((invite.role, invite.max_uses, invite.requires_approval), (Role.DIRECAO.value, 2, True))
        self.assertLess(invite.expires_at - timezone.now(), dt.timedelta(days=3, minutes=1))


class FirstStepsTests(InviteBase):
    def test_new_school_direction_is_guided_until_the_basics_exist(self):
        fresh = School.objects.create(name="Escola Recém-Cadastrada", code="nova")
        invite = invites.create_invite(fresh, Role.DIRECAO.value, self.root)
        self.signup(invite.code)
        self.client.login(username="nova.pessoa", password=PASSWORD)
        page = self.client.get(reverse("pending_center"))
        self.assertContains(page, "Primeiros passos: cadastrar o ano letivo")
        self.assertContains(page, "Primeiros passos: convidar os professores")
        self.client.force_login(self.direc)  # Escola A já tem ano, turma e professor
        self.assertNotContains(self.client.get(reverse("pending_center")), "Primeiros passos")
