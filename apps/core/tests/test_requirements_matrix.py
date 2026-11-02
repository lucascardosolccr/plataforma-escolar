"""A matriz mestra de requisitos (tools/matriz_requisitos.py) não pode citar
evidência que não existe: foi assim que a matriz anterior apontou testes
inventados. Este teste roda a mesma conferência do script."""

import importlib.util
from pathlib import Path

from django.test import SimpleTestCase

SCRIPT = Path(__file__).resolve().parents[3] / "tools" / "matriz_requisitos.py"


class RequirementsMatrixTests(SimpleTestCase):
    def test_every_cited_evidence_exists(self):
        spec = importlib.util.spec_from_file_location("matriz_requisitos", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.validate(), [])
        self.assertGreater(len(mod.REQS), 100)
