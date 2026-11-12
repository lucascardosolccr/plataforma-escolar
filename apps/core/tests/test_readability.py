"""Medidor de legibilidade (core/readability.py)."""

from django.test import TestCase

from apps.core import readability as r


class ReadabilityTests(TestCase):
    def test_syllable_counting_by_vowel_groups(self):
        self.assertEqual(r.syllables("gato"), 2)
        self.assertEqual(r.syllables("comeu"), 2)      # 'o' + 'eu'
        self.assertEqual(r.syllables("casa"), 2)
        self.assertEqual(r.syllables("sol"), 1)
        self.assertEqual(r.syllables("123"), 0)        # sem vogal

    def test_empty_and_short_text(self):
        self.assertIsNone(r.analyze(""))
        self.assertIsNone(r.analyze("   "))
        curto = r.analyze("O gato comeu.")
        self.assertFalse(curto["enough"])              # menos de 10 palavras

    def test_easy_text_scores_high(self):
        # Texto simples, frases curtas: contagens conferidas à mão.
        a = r.analyze("O gato comeu o rato. O rato fugiu do gato. O gato dormiu no sofá.")
        self.assertTrue(a["enough"])
        self.assertEqual(a["sentences"], 3)
        self.assertEqual(a["words"], 15)
        self.assertGreaterEqual(a["score"], 75)
        self.assertEqual(a["band"], "muito fácil")
        self.assertEqual(a["long_count"], 0)

    def test_hard_text_scores_lower_and_flags_long_sentence(self):
        facil = r.analyze("O sol é bom. A lua é bela. O céu é azul. O mar é frio agora.")
        dificil = r.analyze(
            "A operacionalização interdisciplinar das competências socioemocionais pressupõe uma "
            "ressignificação epistemológica contínua das práticas avaliativas institucionalizadas pelos "
            "estabelecimentos educacionais contemporâneos frente às transformações paradigmáticas vigentes "
            "na sociedade globalizada do século vinte e um atual.")
        self.assertLess(dificil["score"], facil["score"])
        self.assertEqual(dificil["long_count"], 1)     # uma frase com mais de 25 palavras
        self.assertIn(dificil["band"], ("difícil", "muito difícil"))
