"""Cruzamento de filtros no painel individual (Prompt 13 §7 e §15).

Clicar numa disciplina no gráfico de médias filtra a página: a evolução
mensal, a distribuição das notas e o histórico de avaliações passam a usar só
as notas daquela disciplina.

Também protege um defeito achado em 02/11/2026: ``id_param`` devolve texto e o
painel o comparava com ``subject_id`` (número), então o clique esvaziava a
tabela de avaliações em vez de filtrá-la.
"""

from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.pedagogy.models import Evaluation, Grade

from .test_bi_access import PW, Q, BIAccessBase


class CrossFilterTests(BIAccessBase):
    def setUp(self):
        super().setUp()
        ev = Evaluation.objects.create(school=self.school, subject=self.por, class_group=self.t1, title="Redação",
                                       date=date(2026, 4, 8), status=Evaluation.Status.PUBLISHED, created_by=self.prof)
        Grade.objects.create(school=self.school, evaluation=ev, student=self.ana, value=Decimal("3"))
        self.client.login(username="direcao", password=PW)
        self.url = reverse("analytics:student_dashboard", args=[self.ana.pk])

    @staticmethod
    def _rows(resp):
        """Corpo da tabela do histórico de avaliações (sem o cabeçalho, que tem a palavra 'avaliação')."""
        return resp.content.decode().split('id="avaliacoes"')[1].split("<tbody>")[1].split("</tbody>")[0]

    def test_subject_bar_links_filter_the_whole_section(self):
        page = self.client.get(self.url + Q)
        self.assertContains(page, f"disciplina={self.mat.pk}#desempenho")
        self.assertIn("Redação", self._rows(page))
        filtered = self.client.get(self.url + Q + f"&disciplina={self.mat.pk}")
        self.assertContains(filtered, "Filtrado por Matemática")
        self.assertEqual([e["evaluation"].title for e in filtered.context["evaluations"]], ["P1"])
        rows = self._rows(filtered)
        self.assertIn("P1", rows)
        self.assertNotIn("Redação", rows)
        # A evolução mensal muda: abril (só a redação) perde o ponto.
        self.assertNotEqual(str(page.context["evolution_chart"]), str(filtered.context["evolution_chart"]))

    def test_distribution_follows_the_filter(self):
        full = str(self.client.get(self.url + Q).context["distribution_chart"])
        filtered = self.client.get(self.url + Q + f"&disciplina={self.por.pk}")
        self.assertContains(filtered, "Filtrado por Português")
        self.assertNotEqual(full, str(filtered.context["distribution_chart"]))
        self.assertEqual([e["evaluation"].title for e in filtered.context["evaluations"]], ["Redação"])


class TeacherPanelFilterTests(BIAccessBase):
    """O mesmo defeito existia no painel do professor: escolher turma ou disciplina esvaziava a tabela."""

    def test_class_and_subject_filters_keep_the_matching_rows(self):
        from apps.academics.models import TeacherAssignment

        TeacherAssignment.objects.create(school=self.school, school_year=self.t1.school_year, teacher=self.prof,
                                         class_group=self.t2, subject=self.mat)
        self.client.login(username="prof", password=PW)
        url = reverse("analytics:teacher_dashboard") + Q
        rows = lambda q: [(r["class_group"].name, r["subject"].name) for r in self.client.get(url + q).context["report"]["rows"]]
        self.assertEqual(sorted(rows("")), [("5º A", "Matemática"), ("5º B", "Matemática")])
        self.assertEqual(rows(f"&turma={self.t2.pk}"), [("5º B", "Matemática")])
        self.assertEqual(len(rows(f"&disciplina={self.mat.pk}")), 2)
        self.assertEqual(rows(f"&disciplina={self.por.pk}"), [])
