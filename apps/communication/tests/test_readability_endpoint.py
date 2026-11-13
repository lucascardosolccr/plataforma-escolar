"""Legibilidade ao vivo nos formulários de comunicado e mensagem à família.

O endpoint só analisa o texto enviado (fonte única do cálculo em apps.core.readability),
é restrito à equipe e não toca em nenhum dado de aluno.
"""

from django.urls import reverse

from apps.communication.tests.test_family_events import PW, FamBase


class ReadabilityEndpointTests(FamBase):
    def url(self):
        return reverse("communication:readability_check")

    def test_staff_gets_index_for_long_text(self):
        self.login(self.prof)
        texto = ("A reunião de pais acontece na próxima terça-feira às dezoito horas "
                 "no salão da escola. Pedimos a presença de todos os responsáveis.")
        resp = self.client.post(self.url(), {"text": texto})
        self.assertEqual(resp.status_code, 200)
        r = resp.json()["readability"]
        self.assertTrue(r["enough"])
        self.assertIn(r["band"], ("muito fácil", "fácil", "difícil", "muito difícil"))
        self.assertIsInstance(r["score"], (int, float))
        self.assertEqual(r["sentences"], 2)

    def test_long_sentence_is_flagged(self):
        self.login(self.prof)
        # Uma única frase com mais de 25 palavras deve ser sinalizada.
        texto = " ".join(["palavra%d" % i for i in range(30)]) + "."
        r = self.client.post(self.url(), {"text": texto}).json()["readability"]
        self.assertEqual(r["long_count"], 1)

    def test_short_text_says_not_enough(self):
        self.login(self.prof)
        r = self.client.post(self.url(), {"text": "Oi, tudo bem?"}).json()["readability"]
        self.assertFalse(r["enough"])
        self.assertEqual(r["min_words"], 10)

    def test_empty_text_is_safe(self):
        self.login(self.prof)
        r = self.client.post(self.url(), {"text": ""}).json()["readability"]
        self.assertTrue(r.get("empty"))

    def test_guardian_is_blocked(self):
        self.login(self.fam)  # responsável não é equipe
        resp = self.client.post(self.url(), {"text": "um texto qualquer com várias palavras aqui"})
        self.assertEqual(resp.status_code, 403)

    def test_get_not_allowed(self):
        self.login(self.prof)
        self.assertEqual(self.client.get(self.url()).status_code, 405)

    def test_announcement_form_shows_readability_hint_for_staff(self):
        self.login(self.prof)
        resp = self.client.get(reverse("communication:announcement_create"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "data-readability")
        self.assertContains(resp, "js/readability.js")

    def test_message_form_shows_readability_hint_for_staff(self):
        self.login(self.prof)
        resp = self.client.get(reverse("communication:thread_create"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-target="id_body"')
