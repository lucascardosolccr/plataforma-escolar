"""Números em frases, no padrão brasileiro (vírgula decimal; sem dado, travessão)."""

import re
from decimal import Decimal

from django.test import SimpleTestCase

from apps.core.fmt import dec, pct


class FmtTests(SimpleTestCase):
    def test_comma_and_missing(self):
        self.assertEqual(dec(0.425), "0,42")  # arredondamento do Python (meio para par em binário)
        self.assertEqual(dec(Decimal("0.5")), "0,50")
        self.assertEqual(dec(2, 1), "2,0")
        self.assertEqual(pct(25.25), "25,2%")
        self.assertEqual(pct(None), "—")
        self.assertEqual(dec(None), "—")

    def test_mastery_reasons_use_comma(self):
        """O "por que este estado" do EIA-Cognitio saía "Média ponderada 0.44"."""
        from datetime import date

        from apps.cognitio.mastery import assess
        from apps.cognitio.models import MasteryScale, SkillEvidence

        evs = [SkillEvidence(pk=i + 1, source_type=SkillEvidence.Source.QUESTION, source_id=i + 1, source_label="Prova",
                             observed_on=date(2026, 3, 2 + 5 * i), ratio=r, weight=1.0)
               for i, r in enumerate((0.4, 0.45, 0.5, 0.42))]
        reasons = " ".join(assess(evs, MasteryScale(), today=date(2026, 3, 30)).reasons)
        self.assertRegex(reasons, r"Média ponderada \d,\d\d")
        self.assertNotRegex(reasons, r"\d\.\d")

    def test_record_names_use_brazilian_dates(self):
        """Nomes de registro aparecem no histórico e nas listas: antes saía "em 2026-03-10"."""
        from datetime import date

        from apps.pedagogy.models import AbsenceJustification, Occurrence
        from apps.registry.models import Student

        ana = Student(first_name="Ana")
        self.assertIn("em 10/03/2026", str(Occurrence(student=ana, date=date(2026, 3, 10))))
        self.assertIn("(02/03/2026 a 04/03/2026)",
                      str(AbsenceJustification(student=ana, start_date=date(2026, 3, 2), end_date=date(2026, 3, 4))))
        self.assertIn("em —", str(Occurrence(student=ana, date=None)))
