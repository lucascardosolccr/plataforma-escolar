"""Painel de legibilidade do enunciado: só a equipe vê; a família, nunca."""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from ..models import Activity
from .test_pedagogy import PedagogyBase


class ReadabilityPanelTests(PedagogyBase):
    def _activity(self, description):
        return Activity.objects.create(
            school=self.school, class_group=self.turma, subject=self.mat, title="Lição",
            description=description, created_by=self.prof, status=Activity.Status.PUBLISHED,
            published_date=timezone.localdate() - timedelta(days=1))

    def test_staff_sees_panel_family_does_not(self):
        act = self._activity("Leia o texto da página dez e responda às cinco perguntas no caderno com calma.")
        url = reverse("pedagogy:activity_detail", args=[act.pk])

        self.login("prof")
        staff = self.client.get(url)
        self.assertEqual(staff.status_code, 200)
        self.assertContains(staff, "Legibilidade")

        self.login("resp")
        family = self.client.get(url)
        self.assertEqual(family.status_code, 200)
        self.assertNotContains(family, "Legibilidade")

    def test_long_sentence_is_flagged_for_staff(self):
        hard = ("A operacionalização interdisciplinar das competências pressupõe uma ressignificação "
                "epistemológica contínua das práticas avaliativas institucionalizadas pelos estabelecimentos "
                "educacionais contemporâneos frente às transformações paradigmáticas vigentes na sociedade atual.")
        act = self._activity(hard)
        self.login("prof")
        resp = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        self.assertContains(resp, "mais de 25 palavras")
