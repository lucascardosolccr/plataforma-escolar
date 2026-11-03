"""Sistema Elo (elo.py): recupera dificuldades conhecidas, prevê sem olhar a resposta e respeita os mínimos."""

import datetime as dt

from django.test import SimpleTestCase
from django.urls import reverse

from apps.cognitio import elo
from apps.cognitio.models import ModelRun
from apps.cognitio.tests.test_evidence import Base


class EloMathTests(SimpleTestCase):
    def test_recovers_known_difficulties_on_synthetic_rasch_data(self):
        self.assertGreater(elo.synthetic_check(), 0.9)

    def test_prediction_is_made_before_seeing_the_answer(self):
        d = dt.date(2026, 3, 1)
        obs = [(d, 1, 10, 1), (d, 1, 10, 0)]
        preds, _ = elo.run_online(obs, 0.8, 0.05)
        self.assertEqual(preds[0], 0.5)  # nada visto ainda
        self.assertGreater(preds[1], 0.5)  # aprendeu com o primeiro acerto, não com o erro que vem a seguir
        changed, _ = elo.run_online([(d, 1, 10, 1), (d, 1, 10, 1)], 0.8, 0.05)
        self.assertEqual(preds, changed)  # a segunda resposta não altera a própria previsão

    def test_uncertainty_function_shrinks_the_step(self):
        d = dt.date(2026, 3, 1)

        def step(n_prior):  # quanto a dificuldade da habilidade 11 muda com mais uma resposta
            prior = [(d, 100 + k, 11, k % 2) for k in range(n_prior)]
            _, before = elo.run_online(prior, 1.0, 0.5)
            _, after = elo.run_online(prior + [(d, 999, 11, 1)], 1.0, 0.5)
            return abs(after["diff"][11] - before["diff"].get(11, 0.0))

        self.assertAlmostEqual(step(0), 0.5)  # a·(1 − 0,5) com K = a
        self.assertGreater(step(0), 2 * step(6))  # K = a/(1 + 0,5·6) = a/4


class EloRunTests(Base):
    def test_small_school_stays_exploratory_and_page_runs_it(self):
        run = elo.train_and_validate(self.school)
        self.assertEqual(run.status, ModelRun.Status.INSUFFICIENT)
        self.login(self.coord)
        self.client.post(reverse("cognitio:models"), {"acao": "treinar_elo"})
        self.assertEqual(ModelRun.objects.filter(name=elo.NAME).count(), 2)
        self.assertContains(self.client.get(reverse("cognitio:models")), "elo_proximo_acerto")
