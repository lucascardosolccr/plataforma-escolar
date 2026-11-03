"""Recuperação de senha por códigos de uso único, sem escola e sem e-mail (Prompt 2 §5.25)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.communication.models import Notification
from apps.core.models import AuditLog, RecoveryCode, Role, School

User = get_user_model()
PW = "Senha-antiga-123"
NEW = "Nova-frase-de-senha-42"


class RecoveryCodeTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        self.user = User.objects.create_user("mae.ana", password=PW, role=Role.RESPONSAVEL, school=self.school)

    def _generate(self):
        self.client.login(username="mae.ana", password=PW)
        resp = self.client.post(reverse("recovery_codes"), {"password": PW})
        self.client.logout()
        return resp.context["codes"]

    def _recover(self, code, username="mae.ana", p1=NEW, p2=NEW):
        return self.client.post(reverse("password_recover"),
                                {"username": username, "code": code, "new_password1": p1, "new_password2": p2})

    def test_generate_needs_current_password_and_stores_only_hashes(self):
        self.client.login(username="mae.ana", password=PW)
        self.client.post(reverse("recovery_codes"), {"password": "errada"})
        self.assertFalse(RecoveryCode.objects.exists())
        codes = self.client.post(reverse("recovery_codes"), {"password": PW}).context["codes"]
        self.assertEqual(len(codes), 8)
        self.assertEqual(len(set(codes)), 8)
        stored = list(RecoveryCode.objects.values_list("code_hash", flat=True))
        self.assertEqual(len(stored), 8)
        for c in codes:
            self.assertRegex(c, r"^[A-Z2-9]{5}-[A-Z2-9]{5}$")
            self.assertNotIn(c.replace("-", ""), "".join(stored))
        # Depois, a página só mostra quantos restam; os códigos não aparecem de novo.
        page = self.client.get(reverse("recovery_codes"))
        self.assertContains(page, "<strong>8</strong> códigos sem uso", html=False)
        self.assertNotContains(page, codes[0])
        self.assertTrue(AuditLog.objects.filter(user=self.user, detail__startswith="Gerou novos códigos").exists())

    def test_recover_with_code_once_and_regenerating_invalidates_old_codes(self):
        codes = self._generate()
        resp = self._recover(codes[0].lower().replace("-", " "))  # aceita minúsculas e espaços
        self.assertRedirects(resp, reverse("login"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW))
        self.assertTrue(Notification.objects.filter(user=self.user, title__contains="código de recuperação").exists())
        self.assertTrue(AuditLog.objects.filter(detail__contains="com um código de recuperação").exists())
        self.assertContains(self.client.get(reverse("login")), "Restam 7 código(s)")
        # O mesmo código não vale de novo.
        self._recover(codes[0], p1="Outra-frase-de-senha-9", p2="Outra-frase-de-senha-9")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW))
        # Gerar outra folha invalida as antigas.
        self.client.login(username="mae.ana", password=NEW)
        self.client.post(reverse("recovery_codes"), {"password": NEW})
        self.client.logout()
        self._recover(codes[1], p1="Outra-frase-de-senha-9", p2="Outra-frase-de-senha-9")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW))

    def test_weak_or_mismatched_password_does_not_spend_the_code(self):
        codes = self._generate()
        self._recover(codes[0], p1="123", p2="123")
        self._recover(codes[0], p1=NEW, p2=NEW + "x")
        self.assertEqual(RecoveryCode.objects.filter(used_at__isnull=True).count(), 8)
        self._recover(codes[0])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW))

    def test_unknown_user_inactive_user_and_wrong_code_get_the_same_message(self):
        codes = self._generate()
        msgs = [self._recover("AAAAA-BBBBB"), self._recover(codes[0], username="nao.existe")]
        self.user.is_active = False
        self.user.save()
        msgs.append(self._recover(codes[0]))
        for r in msgs:
            self.assertContains(r, "Usuário ou código inválido")
        self.assertEqual(RecoveryCode.objects.filter(used_at__isnull=True).count(), 8)

    def test_failures_count_in_the_login_limit_even_with_the_right_code(self):
        codes = self._generate()
        for _ in range(5):
            self._recover("AAAAA-BBBBB")
        resp = self._recover(codes[0])
        self.assertContains(resp, "Muitas tentativas")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PW))

    def test_entry_points(self):
        login = self.client.get(reverse("login"))
        self.assertContains(login, reverse("password_recover"))
        self.assertEqual(self.client.get(reverse("password_recover")).status_code, 200)
        self.assertEqual(self.client.get(reverse("recovery_codes")).status_code, 302)  # exige login
        self.client.login(username="mae.ana", password=PW)
        self.assertContains(self.client.get(reverse("password_change")), reverse("recovery_codes"))
        self.assertRedirects(self.client.get(reverse("password_recover")), reverse("password_change"))
