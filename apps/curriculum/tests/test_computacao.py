"""Complemento de Computação à BNCC (Anexo ao Parecer CNE/CEB nº 2/2022)."""

from django.urls import reverse

from apps.academics.models import Subject
from apps.curriculum.loader import load_bncc
from apps.curriculum.models import CurriculumCorrespondence, CurriculumItem, CurriculumItemVersion, component_for
from apps.curriculum.tests.test_curriculum import Base


class UnitsByPositionTests(Base):
    """Unidades e objetos relidos pela posição na página dupla do PDF (migração 0007)."""

    def test_history_units_whole_and_rows_kept_together(self):
        get = lambda code: CurriculumItem.objects.get(school__isnull=True, code=code)  # noqa: E731
        self.assertEqual(get("EF01HI05").thematic_unit, "Mundo pessoal: eu, meu grupo social e meu tempo")
        self.assertEqual(get("EF09HI01").thematic_unit, "O nascimento da República no Brasil e os processos "
                                                        "históricos até a metade do século XX")
        self.assertEqual(get("EF06HI14").thematic_unit, "Lógicas de organização política")
        self.assertEqual(get("EF01CI02").thematic_unit, "Vida e evolução")
        # dois objetos na mesma linha da tabela valem para todas as habilidades dessa linha
        self.assertEqual(get("EF05HI06").knowledge_object, get("EF05HI09").knowledge_object)
        self.assertIn("O surgimento da escrita", get("EF05HI06").knowledge_object)
        self.assertEqual(get("EF05HI10").knowledge_object, "Os patrimônios materiais e imateriais da humanidade")
        self.assertEqual(get("EF02HI10").knowledge_object, "A sobrevivência e a relação com a natureza")
        self.assertEqual(get("EF69LP11").thematic_unit, "Oralidade")
        self.assertEqual(get("EF01LP05").thematic_unit, "Análise linguística/semiótica (Alfabetização)")
        self.assertFalse(CurriculumItem.objects.filter(school__isnull=True, kind="habilidade", thematic_unit="")
                         .exclude(component="Ensino Religioso").exists())
        self.assertFalse(CurriculumItemVersion.objects.exists())  # o texto oficial não mudou


class ComputingTests(Base):
    def test_official_skills_loaded_with_axis_and_object(self):
        co = CurriculumItem.objects.filter(school__isnull=True, kind="habilidade", component="Computação", active=True)
        self.assertEqual(co.count(), 103)
        h = co.get(code="EF09CO10")
        self.assertEqual(h.text, "Avaliar a veracidade, credibilidade e relevância da informação em seus diferentes "
                                 "formatos, sendo capaz de identificar o propósito pelo qual foi disseminada.")
        self.assertEqual((h.thematic_unit, h.knowledge_object, h.year_list),
                         ("Cultura digital", "Uso de tecnologias computacionais: Qualidade da informação", [9]))
        self.assertEqual(co.get(code="EF15CO01").year_list, [1, 2, 3, 4, 5])
        self.assertEqual(co.get(code="EF69CO12").year_list, [6, 7, 8, 9])
        self.assertEqual(set(co.values_list("thematic_unit", flat=True)),
                         {"Pensamento computacional", "Mundo digital", "Cultura digital"})
        c = CurriculumCorrespondence.objects.get(source=h, target__code="PNED-III")
        self.assertEqual((c.origin, c.confidence, c.validated), ("automatica", "media", False))

    def test_bncc_reload_keeps_computing_active(self):
        load_bncc(CurriculumItem, CurriculumItemVersion)
        self.assertEqual(CurriculumItem.objects.filter(component="Computação", active=True).count(), 103)

    def test_subject_and_pair(self):
        for name in ("Computação", "Informática", "Pensamento Computacional"):
            self.assertEqual(component_for(Subject(school=self.school, name=name)), "Computação", name)
        codes = set(CurriculumItem.for_pair(self.school, "Computação", 6).values_list("code", flat=True))
        self.assertTrue({"EF06CO01", "EF69CO01"} <= codes)
        self.assertNotIn("EF07CO01", codes)
        self.login(self.prof)
        r = self.client.get(reverse("curriculum:catalog"), {"componente": "Computação", "ano": "6"})
        self.assertContains(r, "EF06CO01")
