"""Tipos de autorização: uso de imagem e saída sozinho valem por um período, podem ser retirados a qualquer momento
e alimentam a lista de fotos e a tela de retirada."""

import datetime as dt
from unittest import mock

from django.urls import reverse

from apps.care.models import PickupRecord
from apps.gate.models import GateEvent

from ..consents import allowed, standing
from ..models import Authorization, AuthorizationSignature, Notification
from . import test_authorizations as base


class KindTests(base.AuthorizationTests):
    test_teacher_creates_for_own_class_and_only_those_families_are_notified = None
    test_family_answers_changes_and_staff_sees_counts_and_printable_list = None
    test_refusals = None
    test_cancel_needs_reason_and_notifies = None

    def ongoing(self, kind="imagem", **extra):
        data = {"kind": kind, "title": "Fotos e vídeos de 2026" if kind == "imagem" else "Saída sozinho(a)",
                "description": "Mural da escola e site, durante o ano letivo.",
                "event_date": self.today.isoformat(), "deadline": (self.today + dt.timedelta(days=1)).isoformat(),
                "valid_until": (self.today + dt.timedelta(days=100)).isoformat(), **extra}
        return self._create(**data)

    def later(self, days):
        """Só a data anda (a sessão continua válida, o relógio não)."""
        return mock.patch("django.utils.timezone.localdate", return_value=self.today + dt.timedelta(days=days))

    def test_trip_text_is_unchanged_so_old_signatures_still_check(self):
        auth = self._create()
        self.assertEqual(auth.kind, "passeio")
        self.assertEqual(auth.document_text(),
                         f"Escola A\nAutorização: Passeio ao Zoológico\nTurmas: {self.turma.name}\n"
                         f"Data da atividade: {auth.event_date:%d/%m/%Y}\nResponder até: {auth.deadline:%d/%m/%Y}\n\n"
                         f"Saída 8h, volta 12h. Levar lanche.")

    def test_ongoing_kind_needs_an_end_date_and_says_it_can_be_withdrawn(self):
        self.assertIsNone(self.ongoing(valid_until=""))
        self.assertIsNone(self.ongoing(valid_until=(self.today - dt.timedelta(days=1)).isoformat()))
        self.assertIsNone(self.ongoing(deadline=(self.today + dt.timedelta(days=200)).isoformat()))
        auth = self.ongoing()
        text = auth.document_text()
        self.assertIn("Tipo: Uso de imagem e voz", text)
        self.assertIn("pode retirar esta autorização a qualquer momento", text)
        trip = self._create(title="Visita", valid_until=(self.today + dt.timedelta(days=30)).isoformat())
        self.assertIsNone(trip.valid_until)  # passeio não guarda "vale até"

    def test_photo_list_shows_only_valid_signed_consent(self):
        auth = self.ongoing()
        self.login("prof")
        self.assertContains(self.client.get(reverse("communication:authorization_images")),
                            f'{self.ana.full_name} <span class="small text-body-secondary">· sem resposta')
        self.login("resp")
        self._answer(auth, "autorizo")
        sig = AuthorizationSignature.objects.get()
        self.assertTrue(standing(self.school, "imagem", [self.ana.pk])[self.ana.pk]["granted"])
        self.login("prof")
        page = self.client.get(reverse("communication:authorization_images"))
        self.assertContains(page, sig.display_code)
        self.assertNotContains(page, "Nenhuma autorização de uso de imagem valendo hoje")
        # Alterada no banco: deixa de valer e a lista mostra o motivo.
        AuthorizationSignature.objects.filter(pk=sig.pk).update(note="mexido")
        self.assertContains(self.client.get(reverse("communication:authorization_images")), "registro adulterado")
        self.assertIsNone(allowed(self.ana, "imagem"))
        self.login("resp")
        self.assertEqual(self.client.get(reverse("communication:authorization_images")).status_code, 403)

    def test_text_changed_after_signing_stops_the_consent(self):
        auth = self.ongoing()
        self.login("resp")
        self._answer(auth, "autorizo")
        Authorization.objects.filter(pk=auth.pk).update(description="Agora também em propaganda paga.")
        row = standing(self.school, "imagem", [self.ana.pk])[self.ana.pk]
        self.assertEqual((row["granted"], row["reason"]), (False, "assinou uma versão anterior do texto"))

    def test_family_can_withdraw_after_the_deadline_and_the_school_is_told(self):
        auth = self.ongoing()
        self.login("resp")
        self._answer(auth, "autorizo")
        sign = reverse("communication:authorization_sign", args=[auth.pk, self.ana.pk])
        with self.later(3):
            self.assertFalse(auth.accepts_answers())
            self.assertContains(self.client.get(reverse("communication:authorization_detail", args=[auth.pk])),
                                "Retirar a autorização")
            self.assertContains(self._answer(auth, "autorizo"), "só é possível retirar")
            self._answer(auth, "nao_autorizo")
            self.assertEqual(AuthorizationSignature.objects.count(), 2)
            self.assertIsNone(allowed(self.ana, "imagem"))
            self.assertEqual(standing(self.school, "imagem", [self.ana.pk])[self.ana.pk]["reason"],
                             "a família não autorizou")
            n = Notification.objects.get(user=self.prof, title__startswith="Autorização retirada")
            self.assertEqual(n.priority, "importante")
            self.assertTrue(Notification.objects.filter(user=self.direc, title__startswith="Autorização retirada")
                            .exists())
            # Retirada já feita: não há mais o que assinar depois do prazo.
            self.assertRedirects(self.client.get(sign), reverse("communication:authorization_detail", args=[auth.pk]))
        with self.later(101):  # fim da validade: ninguém mais está autorizado
            self.assertIsNone(allowed(self.ana, "imagem"))

    def test_trip_cannot_be_changed_after_the_deadline(self):
        auth = self._create()
        self.login("resp")
        self._answer(auth, "autorizo")
        with self.later(6):
            sign = reverse("communication:authorization_sign", args=[auth.pk, self.ana.pk])
            self.assertRedirects(self.client.get(sign), reverse("communication:authorization_detail", args=[auth.pk]))

    def test_alone_exit_only_with_valid_signed_authorization(self):
        auth = self.ongoing("saida")
        url = reverse("care:register", args=[self.ana.pk])
        self.login("sec")
        self.assertNotContains(self.client.get(url), 'value="s:"')
        self.client.post(url, {"quem": "s:"})  # sem autorização: não registra
        self.assertFalse(PickupRecord.objects.exists())
        self.login("resp")
        self._answer(auth, "autorizo")
        sig = AuthorizationSignature.objects.get()
        self.assertContains(self.client.get(reverse("care:pickups", args=[self.ana.pk])), sig.display_code)
        self.login("sec")
        self.assertContains(self.client.get(url), 'value="s:"')
        self.client.post(url, {"quem": "s:"})
        rec = PickupRecord.objects.get()
        self.assertEqual((rec.kind, rec.person_name), ("sozinho", "sozinho(a)"))
        self.assertIn(sig.display_code, rec.verification)
        self.assertTrue(GateEvent.objects.filter(student=self.ana, kind="saida").exists())
        self.assertTrue(Notification.objects.filter(user=self.resp, title__contains="sozinho(a)").exists())

    def test_alone_option_disappears_when_tampered(self):
        auth = self.ongoing("saida")
        self.login("resp")
        self._answer(auth, "autorizo")
        AuthorizationSignature.objects.update(student=self.bea)  # trocou o estudante no banco
        AuthorizationSignature.objects.update(student=self.ana, signer_name="Outra Pessoa")
        self.login("sec")
        self.assertNotContains(self.client.get(reverse("care:register", args=[self.ana.pk])), 'value="s:"')
        self.client.post(reverse("care:register", args=[self.ana.pk]), {"quem": "s:"})
        self.assertFalse(PickupRecord.objects.exists())

    def test_canceled_authorization_stops_counting(self):
        auth = self.ongoing("saida")
        self.login("resp")
        self._answer(auth, "autorizo")
        self.assertIsNotNone(allowed(self.ana, "saida"))
        Authorization.objects.filter(pk=auth.pk).update(status="cancelada")
        self.assertIsNone(allowed(self.ana, "saida"))
