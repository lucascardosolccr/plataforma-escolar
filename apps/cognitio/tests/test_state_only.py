"""state_only (evolução por período do painel) dá exatamente o estado de assess.

Conferido também na base de escala (09/11/2026): 87.048 pares × datas de corte, nenhuma diferença; o painel
caiu de ~1,3 s para ~0,6 s com o mesmo HTML.
"""

import datetime
import random
from bisect import bisect_right
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.cognitio.mastery import assess, sort_key, state_only
from apps.cognitio.models import MasteryScale

D0 = datetime.date(2026, 2, 2)


def ev(pk, days, ratio, weight=1.0):
    return SimpleNamespace(pk=pk, observed_on=D0 + datetime.timedelta(days=days), ratio=ratio, weight=weight,
                           source_type="questao")


class StateOnlyTests(SimpleTestCase):
    def check(self, evs, scale, end):
        ordered = sorted(evs, key=sort_key)
        cut = ordered[:bisect_right([e.observed_on for e in ordered], end)]
        expected = assess([e for e in evs if e.observed_on <= end], scale, end, explain=False).state
        self.assertEqual(state_only(cut, scale, end), expected, (evs, end))

    def test_matches_assess_on_random_evidence_and_cutoffs(self):
        rnd = random.Random(20261109)
        scales = [MasteryScale(), MasteryScale(min_evidence=1, min_weight=Decimal("0.5"), half_life_days=30),
                  MasteryScale(t1=Decimal("0.5"), t2=Decimal("0.7"), t3=Decimal("0.9"), half_life_days=0)]
        for _ in range(3000):
            n = rnd.randrange(0, 9)
            evs = [ev(rnd.randrange(1, 10**6), rnd.randrange(0, 280),
                      None if rnd.random() < 0.15 else rnd.choice([0, 0.25, 0.4, 0.5, 0.6, 0.75, 0.8, 1, rnd.random()]),
                      rnd.choice([0, 0.3, 0.5, 1.0, 1.5])) for _ in range(n)]
            self.check(evs, rnd.choice(scales), D0 + datetime.timedelta(days=rnd.randrange(-5, 320)))

    def test_boundary_cases(self):
        scale = MasteryScale()
        cases = [
            [],                                                     # sem evidência
            [ev(1, 0, None), ev(2, 3, None)],                       # só ausências
            [ev(1, 0, 1.0, 0.0), ev(2, 3, 1.0, 0.0)],               # peso zero
            [ev(1, 0, 0.0), ev(2, 1, 1.0), ev(3, 2, 0.0), ev(4, 3, 1.0)],  # contraditória
            [ev(1, 0, float(scale.t1)), ev(2, 0, float(scale.t1)), ev(3, 0, float(scale.t1))],  # exatamente no corte
            [ev(i, i, 0.9) for i in range(6)],                      # consolidada
        ]
        for evs in cases:
            for end in (D0, D0 + datetime.timedelta(days=2), D0 + datetime.timedelta(days=400)):
                self.check(evs, scale, end)
