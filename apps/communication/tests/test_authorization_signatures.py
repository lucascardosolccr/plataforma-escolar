"""Assinatura eletrônica das autorizações: cada proteção contra fraude tem um teste."""

import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.models import Role
from apps.registry.models import GuardianLink

from .. import signatures
from ..models import Authorization, AuthorizationResponse, AuthorizationSignature, Notification
from . import test_authorizations as base


class SignatureTests(base.AuthorizationTests):
    test_teacher_creates_for_own_class_and_only_those_families_are_notified = None
    test_family_answers_changes_and_staff_sees_counts_and_printable_list = None
    test_refusals = None
    test_cancel_needs_reason_and_notifies = None

    def setUp(self):
        super().setUp()
        self.auth = self._create()
        self.login("resp")

    def sign_url(self, student=None):
        return reverse("communication:authorization_sign", args=[self.auth.pk, (student or self.ana).pk])

    def token(self):
        page = self.client.get(self.sign_url())
        return re.search(r'name="token" value="([^"]+)"', page.content.decode()).group(1)

    def post(self, token=None, **extra):
        data = {"token": token or self.token(), "answer": "autorizo", "nome": "Rita Souza", "senha": "senha-forte-1",
                "ciente": "on", **extra}
        return self.client.post(self.sign_url(), data)

    # --- quem assina ---

    def test_wrong_password_is_refused_and_five_lock_and_warn(self):
        for _ in range(4):
            self.assertContains(self.post(senha="errada"), "Senha incorreta")
        self.assertContains(self.post(senha="errada"), "bloqueada por 15 minutos")
        self.assertContains(self.post(), "bloqueada por 15 minutos")  # nem com a senha certa
        self.assertFalse(AuthorizationSignature.objects.exists())
        self.assertTrue(Notification.objects.filter(user=self.resp, title="Assinatura bloqueada por senhas erradas",
                                                    priority="importante").exists())

    def test_name_must_match_the_account_ignoring_accents_and_case(self):
        get_user_model().objects.filter(pk=self.resp.pk).update(first_name="Rita", last_name="Conceição")
        self.assertContains(self.post(nome="Fulano de Tal"), "como está na sua conta")
        self.assertContains(self.post(nome="Rita"), "como está na sua conta")
        self.post(nome="  rita   CONCEICAO ")
        self.assertEqual(AuthorizationSignature.objects.get().signer_name, "rita   CONCEICAO")

    def test_without_account_name_needs_two_words_and_must_confirm_reading(self):
        self.assertContains(self.post(nome="Rita"), "nome e sobrenome")
        self.assertContains(self.post(ciente=""), "Confirme que leu")
        self.assertFalse(AuthorizationSignature.objects.exists())

    def test_student_and_other_family_cannot_sign(self):
        aluna = get_user_model().objects.create_user("aluna", password="senha-forte-1", role=Role.ESTUDANTE,
                                                     school=self.school)
        self.ana.user = aluna
        self.ana.save()
        self.login("aluna")
        self.assertEqual(self.client.get(self.sign_url()).status_code, 403)
        self.login("resp_bea")
        self.assertEqual(self.client.get(self.sign_url()).status_code, 403)

    # --- o formulário ---

    def test_token_is_single_use_and_bound_to_the_student(self):
        token = self.token()
        self.post(token)
        self.assertContains(self.post(token, answer="nao_autorizo"), "já foi usada")
        self.assertEqual(AuthorizationSignature.objects.count(), 1)
        other = signatures.issue_token(self.resp, self.auth, self.bea)
        self.assertContains(self.post(other), "Não foi possível conferir")
        self.assertContains(self.post("lixo"), "Não foi possível conferir")

    def test_expired_token(self):
        token = self.token()
        with mock.patch.object(signatures, "TOKEN_MAX_AGE", -1):
            self.assertContains(self.post(token), "mais de 30 minutos")

    def test_text_changed_while_reading_is_refused(self):
        token = self.token()
        Authorization.objects.filter(pk=self.auth.pk).update(event_date=self.auth.event_date.replace(day=1)
                                                             if self.auth.event_date.day != 1 else
                                                             self.auth.event_date.replace(day=2))
        self.assertContains(self.post(token), "alterou o texto")

    # --- depois de assinar ---

    def test_all_guardians_are_told_with_the_receipt_code(self):
        other = get_user_model().objects.create_user("pai", password="senha-forte-1", role=Role.RESPONSAVEL,
                                                     school=self.school)
        GuardianLink.objects.create(school=self.school, guardian=other, student=self.ana, status="aprovado")
        resp = self.post(note="Leva o remédio")
        sig = AuthorizationSignature.objects.get()
        self.assertRedirects(resp, reverse("communication:authorization_receipt", args=[sig.code]))
        for u in (self.resp, other):
            n = Notification.objects.get(user=u, title__startswith="Autorização assinada")
            self.assertIn(sig.display_code, n.body)
            self.assertIn("Não foi você?", n.body)
        r = AuthorizationResponse.objects.get()
        self.assertEqual((r.answer, r.note, r.signature), ("autorizo", "Leva o remédio", sig))
        self.assertEqual(sig.document, self.auth.document_text())

    def test_changing_the_answer_keeps_the_old_signature_chained(self):
        self.post()
        self.post(answer="nao_autorizo")
        first, second = AuthorizationSignature.objects.order_by("pk")
        self.assertEqual(second.prev_hash, first.seal)
        self.assertEqual(AuthorizationResponse.objects.get().signature, second)
        checks, broken = signatures.verify_all(self.auth)
        self.assertEqual(broken, 0)
        self.assertFalse(checks[first.pk]["current"])
        self.assertTrue(checks[second.pk]["ok"] and checks[second.pk]["current"])

    def test_tampering_in_the_database_is_detected(self):
        self.post()
        self.post(answer="nao_autorizo")
        first, second = AuthorizationSignature.objects.order_by("pk")
        AuthorizationSignature.objects.filter(pk=second.pk).update(answer="autorizo")  # trocou a resposta no banco
        self.assertFalse(signatures.verify(AuthorizationSignature.objects.get(pk=second.pk))["seal_ok"])
        self.login("prof")
        self.assertContains(self.client.get(reverse("communication:authorization_detail", args=[self.auth.pk])),
                            "adulterado")
        # Apagar a primeira (que não é a que vale) quebra a sequência da segunda.
        AuthorizationSignature.objects.filter(pk=second.pk).update(answer="nao_autorizo")
        AuthorizationResponse.objects.all().delete()
        AuthorizationSignature.objects.filter(pk=first.pk).delete()
        self.assertFalse(signatures.verify(AuthorizationSignature.objects.get(pk=second.pk))["chain_ok"])
        # Trocar a cópia do texto também aparece.
        AuthorizationSignature.objects.filter(pk=second.pk).update(prev_hash="", document="Outro texto")
        self.assertFalse(signatures.verify(AuthorizationSignature.objects.get(pk=second.pk))["seal_ok"])

    def test_text_changed_after_signing_asks_for_a_new_signature(self):
        self.post()
        Authorization.objects.filter(pk=self.auth.pk).update(description="Saída 7h, volta 18h, outro lugar.")
        sig = AuthorizationSignature.objects.get()
        check = signatures.verify(sig)
        self.assertTrue(check["seal_ok"] and check["chain_ok"])
        self.assertFalse(check["doc_ok"])
        self.assertContains(self.client.get(reverse("communication:authorization_receipt", args=[sig.code])),
                            "versão anterior do texto")
        self.login("prof")
        self.assertContains(self.client.get(reverse("communication:authorization_detail", args=[self.auth.pk])),
                            "Peça às famílias que assinem de novo")

    def test_receipt_access_and_verification_by_code(self):
        self.post()
        sig = AuthorizationSignature.objects.get()
        receipt = reverse("communication:authorization_receipt", args=[sig.code])
        self.assertContains(self.client.get(receipt), "Assinatura íntegra e válida")
        self.login("prof")
        typed = f"{sig.code[:5].lower()}-{sig.code[5:]}"
        self.assertRedirects(self.client.get(reverse("communication:authorization_verify") + f"?codigo={typed}"),
                             receipt)
        self.login("resp_bea")
        self.assertEqual(self.client.get(receipt).status_code, 403)
        self.assertContains(self.client.get(reverse("communication:authorization_verify") + f"?codigo={sig.code}"),
                            "Comprovante não encontrado")
        self.login("resp_b")
        self.assertEqual(self.client.get(receipt).status_code, 403)

    def test_old_quick_answer_no_longer_records(self):
        resp = self.client.post(reverse("communication:authorization_answer", args=[self.auth.pk]),
                                {"student": self.ana.pk, "answer": "autorizo"})
        self.assertRedirects(resp, self.sign_url())
        self.assertFalse(AuthorizationResponse.objects.exists())

    # --- equipe ---

    def test_remind_only_who_did_not_answer_once_a_day(self):
        self.login("prof")
        url = reverse("communication:authorization_remind", args=[self.auth.pk])
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(Notification.objects.filter(user=self.resp, title__startswith="Lembrete").count(), 1)
        self.login("resp")
        self.post()
        Notification.objects.filter(title__startswith="Lembrete").delete()
        self.login("prof")
        self.client.post(url)
        self.assertFalse(Notification.objects.filter(title__startswith="Lembrete").exists())
        self.login("sec")  # não criou nem é direção
        self.assertEqual(self.client.post(url).status_code, 403)

    def test_printed_list_has_codes_health_alerts_and_emergency_contact(self):
        from apps.care.models import EmergencyContact, HealthRecord

        HealthRecord.objects.create(school=self.school, student=self.ana, allergies="Amendoim")
        EmergencyContact.objects.create(student=self.ana, name="Maria", relationship="mãe", phone="(11) 9999-0000")
        self.post()
        sig = AuthorizationSignature.objects.get()
        self.login("prof")
        page = self.client.get(reverse("communication:authorization_detail", args=[self.auth.pk]) + "?imprimir=1")
        self.assertContains(page, sig.display_code)
        self.assertContains(page, "alergia: Amendoim")
        self.assertContains(page, "(11) 9999-0000")
