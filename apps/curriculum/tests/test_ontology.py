"""Ontologia curricular, PNED, matriz analítica e curadoria (Prompt 16, etapa 2)."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import AuditLog
from apps.curriculum.loader import load_bncc
from apps.curriculum.models import (CurriculumCorrespondence, CurriculumItem, CurriculumItemVersion, ItemDimension,
                                    SkillDimension)
from apps.curriculum.tests.test_curriculum import Base


class OntologyLoadTests(Base):
    def test_structure_from_official_text(self):
        h = CurriculumItem.objects.get(code="EF04CI01")
        self.assertEqual((h.area, h.component, h.thematic_unit), ("Ciências da Natureza", "Ciências", "Matéria e energia"))
        self.assertIn("Misturas", h.knowledge_object)
        self.assertTrue(h.structure_auto)
        self.assertEqual(h.curriculum_version, "BNCC — versão final (2018)")
        self.assertEqual(CurriculumItem.objects.get(code="EF35LP04").thematic_unit,
                         "Leitura/escuta (compartilhada e autônoma)")
        units = set(CurriculumItem.objects.filter(component="Matemática", kind="habilidade")
                    .values_list("thematic_unit", flat=True))
        self.assertTrue({"Números", "Álgebra", "Geometria", "Grandezas e medidas",
                         "Probabilidade e estatística"} <= units)

    def test_specific_competencies_and_pned(self):
        spec = CurriculumItem.objects.filter(kind="competencia_especifica")
        self.assertEqual(spec.count(), 84)
        self.assertEqual(spec.filter(component="Matemática").count(), 8)
        self.assertEqual(spec.filter(component="", area="Ciências Humanas").count(), 7)
        self.assertTrue(spec.get(code="CE-MA-02").text.startswith("Desenvolver o raciocínio lógico"))
        pned = CurriculumItem.objects.filter(kind="competencia_digital")
        self.assertEqual(pned.count(), 5)
        self.assertTrue(pned.get(code="PNED-I").text.startswith("pensamento computacional, que se refere"))
        c = CurriculumCorrespondence.objects.get(source__code="EF06MA04", target__code="PNED-I")
        self.assertEqual((c.origin, c.confidence, c.validated), ("automatica", "baixa", False))

    def test_dimensions_suggested_by_official_words(self):
        self.assertGreaterEqual(SkillDimension.objects.values("component").distinct().count(), 10)
        inference = SkillDimension.objects.get(component="Língua Portuguesa", name="Inferência")
        self.assertTrue(ItemDimension.objects.filter(dimension=inference, item__code="EF35LP04", validated=False).exists())

    def test_reload_keeps_history_when_text_changes(self):
        h = CurriculumItem.objects.get(code="EF06MA01")
        official = h.text
        h.text = "Texto alterado por engano"
        h.save()
        load_bncc(CurriculumItem, CurriculumItemVersion)
        h.refresh_from_db()
        self.assertEqual(h.text, official)
        self.assertEqual(CurriculumItemVersion.objects.get(item=h).text, "Texto alterado por engano")


class CurationTests(Base):
    def test_map_and_curation_permissions(self):
        self.login(self.prof)
        r = self.client.get(reverse("curriculum:ontology_map"))
        self.assertContains(r, "Educação digital escolar")
        self.assertContains(r, "Probabilidade e estatística")
        h = CurriculumItem.objects.get(code="EF35LP04")
        link = ItemDimension.objects.filter(item=h).first()
        url = reverse("curriculum:item_curate", args=[h.pk])
        self.assertEqual(self.client.post(url, {"acao": "dimensao", "id": link.pk}).status_code, 403)
        self.login(self.fam)
        self.assertEqual(self.client.get(reverse("curriculum:ontology_map")).status_code, 403)
        self.login(self.coord)
        self.client.post(url, {"acao": "dimensao", "id": link.pk, "decisao": "validar"})
        link.refresh_from_db()
        self.assertTrue(link.validated)
        self.client.post(url, {"acao": "nota", "nota": "Na escola: inferência a partir de pistas do texto."})
        h.refresh_from_db()
        self.assertEqual(h.operational_note, "Na escola: inferência a partir de pistas do texto.")
        self.assertTrue(h.text.startswith("Inferir informações implícitas"))  # texto oficial intacto
        c = CurriculumCorrespondence.objects.filter(source__code="EF06MA04").first()
        m = CurriculumItem.objects.get(code="EF06MA04")
        self.client.post(reverse("curriculum:item_curate", args=[m.pk]),
                         {"acao": "correspondencia", "id": c.pk, "decisao": "rejeitar"})
        c.refresh_from_db()
        self.assertTrue(c.rejected)
        self.assertTrue(AuditLog.objects.filter(user=self.coord, target_type="CurriculumItem").exists())
        r = self.client.get(reverse("curriculum:item_detail", args=[h.pk]))
        self.assertContains(r, "Leitura/escuta (compartilhada e autônoma)")
        self.assertContains(r, "extração automática")

    def test_import_creates_correspondence_to_validate(self):
        self.login(self.coord)
        csv_text = ("tipo;codigo;componente;anos;texto;fonte;url;habilidades_bncc;relacao;confianca\n"
                    "objetivo_df;DF-MA6-02;Matemática;6;Comparar números;CM-DF, p. 2;;EF06MA01;parcial;alta\n")
        self.client.post(reverse("curriculum:item_import"),
                         {"file": SimpleUploadedFile("c.csv", csv_text.encode("utf-8"))})
        c = CurriculumCorrespondence.objects.get(source__code="DF-MA6-02")
        self.assertEqual((c.target.code, c.relation, c.confidence, c.origin, c.validated),
                         ("EF06MA01", "parcial", "alta", "importacao", False))
