"""Acessibilidade dos gráficos SVG gerados no servidor (leitor de tela).

Os gráficos já nascem acessíveis (role, aria-label com os valores, <title> por
ponto). Este teste trava esse comportamento: um refactor não pode remover em
silêncio o que o leitor de tela anuncia."""

from django.test import SimpleTestCase

from .. import charts


class ChartAccessibilityTests(SimpleTestCase):
    def test_bar_chart_has_img_role_and_value_summary(self):
        svg = str(charts.bar_chart(
            [{"label": "Matemática", "value": 7.5}, {"label": "Português", "value": 6}]))
        self.assertIn('role="img"', svg)
        self.assertIn('aria-label="', svg)
        self.assertIn("Matemática: 7,5", svg)  # resumo acessível com o valor, vírgula decimal
        self.assertIn("<title>", svg)           # valor por barra, para o leitor de tela

    def test_clickable_bars_are_a_group_of_links(self):
        svg = str(charts.bar_chart([{"label": "1º A", "value": 90, "url": "/x/"}], suffix="%"))
        self.assertIn('role="group"', svg)       # não "img": há links dentro
        self.assertIn('<a href="/x/"', svg)
        self.assertIn("ver registros", svg)      # link com rótulo descritivo

    def test_line_chart_has_img_role_and_values(self):
        svg = str(charts.line_chart([{"label": "Mar", "value": 8}, {"label": "Abr", "value": 9}]))
        self.assertIn('role="img"', svg)
        self.assertIn("Mar: 8", svg)

    def test_empty_data_is_a_safe_message_not_a_crash(self):
        self.assertIn("Sem dados", str(charts.bar_chart([])))
        self.assertIn("Sem dados", str(charts.line_chart([])))

    def test_decorative_svg_is_hidden_but_value_is_in_text(self):
        html = str(charts.gauge(92.0, limit=25, label="frequência"))
        self.assertIn('aria-hidden="true"', html)   # a barra é decorativa
        self.assertIn("92% frequência", html)        # o valor fica legível em texto
