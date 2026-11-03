"""Lista de intervenções paginada: antes só as 60 mais recentes apareciam, sem aviso."""

from datetime import timedelta

from django.urls import reverse

from apps.cognitio.models import LearningIntervention

from .test_p17 import P17Base


class InterventionListPagingTests(P17Base):
    def test_every_intervention_is_reachable_and_the_count_is_real(self):
        for i in range(25):
            LearningIntervention.objects.create(
                school=self.school, class_group=self.cg, subject=self.mat, item=self.h1, title=f"Retomada {i:02d}",
                objective="o", activity="a", starts_on=self.today - timedelta(days=5), review_on=self.today,
                created_by=self.prof, status="concluida")
        self.login(self.prof)
        url = reverse("cognitio:interventions") + "?situacao=concluida"
        first = self.client.get(url)
        self.assertEqual(len(first.context["rows"]), 20)
        self.assertEqual(first.context["page"].paginator.count, 25)
        second = self.client.get(url + "&pagina=2")
        titles = {r["iv"].title for r in first.context["rows"]} | {r["iv"].title for r in second.context["rows"]}
        self.assertEqual(len(titles), 25)
