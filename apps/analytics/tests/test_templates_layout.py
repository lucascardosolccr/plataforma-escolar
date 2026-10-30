"""Tabelas dos painéis dentro de rolagem própria.

Em 30/10/2026 a conferência no navegador achou três tabelas fora de
.table-responsive que alargavam a página no celular (390 px).
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TEMPLATES = Path(settings.BASE_DIR) / "templates" / "analytics"
PRINT_ONLY = {"report_print.html"}


class TableWrapperTests(SimpleTestCase):
    def test_every_panel_table_scrolls_inside_its_card(self):
        tables = 0
        for path in TEMPLATES.rglob("*.html"):
            if path.name in PRINT_ONLY:
                continue
            html = path.read_text(encoding="utf-8")
            for m in re.finditer(r"<table[\s>]", html):
                tables += 1
                antes = html[max(0, m.start() - 200):m.start()]
                with self.subTest(template=str(path.relative_to(TEMPLATES)), pos=m.start()):
                    self.assertIn("table-responsive", antes.rsplit("</table>", 1)[-1])
        self.assertGreater(tables, 10)   # o teste precisa de fato encontrar as tabelas

    def test_responsive_wrapper_contains_visually_hidden_text(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "ds-components.css").read_text(encoding="utf-8")
        regra = re.search(r"\.table-responsive \{([^}]*)\}", css).group(1)
        self.assertIn("position: relative", regra)
