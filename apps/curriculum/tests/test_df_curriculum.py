"""Currículo em Movimento do DF incluído na plataforma: dados, importação, sugestões e curadoria."""

from unittest import mock

from django.urls import reverse

from apps.core.models import AuditLog, School
from apps.curriculum import df_curriculum
from apps.curriculum.models import COMPONENTS, CurriculumCorrespondence, CurriculumItem, CurriculumItemVersion
from apps.curriculum.tests.test_curriculum import Base


def _subset(codes):
    data = df_curriculum.dataset()
    return {"meta": data["meta"], "itens": [r for r in data["itens"] if r["codigo"] in codes]}


class DatasetTests(Base):
    def test_extracted_file_is_consistent(self):
        data = df_curriculum.dataset()
        rows = data["itens"]
        self.assertEqual(len(rows), 4284)
        self.assertEqual(len({r["codigo"] for r in rows}), len(rows))
        self.assertTrue(all(r["componente"] in COMPONENTS for r in rows))
        self.assertEqual({r["ano"] for r in rows}, set(range(1, 10)))
        self.assertFalse([r for r in rows if "�" in r["texto"] + r["unidade"] + r["subtitulo"]])
        self.assertTrue(all(r["texto"] and 1 <= r["pagina_pdf"] <= 312 for r in rows))
        self.assertEqual(len(data["meta"]["sha256_pdf"]), 64)
        # amostra conferida com a página 200 do PDF (Matemática, 8º ano)
        mat8 = [r for r in rows if r["codigo"].startswith("CMDF-MA08-O")]
        self.assertTrue(mat8[0]["texto"].startswith("Solucionar cálculos com potências de expoentes inteiros"))
        self.assertEqual(mat8[0]["unidade"], "Números")
        pot = next(r for r in rows if r["codigo"].startswith("CMDF-MA08-C") and r["texto"] == "Definição e identificação")
        self.assertEqual((pot["unidade"], pot["subtitulo"]), ("Números", "Potenciação e radiciação"))


class ImportTests(Base):
    def test_full_import_then_reimport_keeps_school_decisions(self):
        r = df_curriculum.import_for_school(self.school, self.coord)
        self.assertEqual(r["created"], 4284)
        items = CurriculumItem.objects.filter(school=self.school, code__startswith="CMDF-")
        self.assertFalse(items.filter(needs_review=False).exists())
        self.assertTrue(items.filter(kind="objetivo_df", component="Matemática", years="6").exists())
        sug = CurriculumCorrespondence.objects.filter(school=self.school, origin="automatica")
        self.assertGreater(sug.count(), 500)
        self.assertFalse(sug.exclude(target__kind="habilidade").exists())
        self.assertFalse(sug.filter(validated=True).exists())
        for c in sug.select_related("source", "target")[:200]:
            self.assertEqual(c.source.component, c.target.component)
            self.assertIn(int(c.source.years), c.target.year_list)
        # a escola confere um texto, rejeita uma sugestão e valida outra
        fixed = items.get(code="CMDF-MA08-O001")
        fixed.text, fixed.needs_review = "Texto corrigido pela coordenação", False
        fixed.save()
        rejected, validated = list(sug.order_by("pk")[:2])
        rejected.rejected = True
        rejected.save()
        validated.validated, validated.confidence = True, "alta"
        validated.save()
        r2 = df_curriculum.import_for_school(self.school, self.coord)
        self.assertEqual((r2["created"], r2["kept"]), (0, 1))
        fixed.refresh_from_db()
        self.assertEqual(fixed.text, "Texto corrigido pela coordenação")
        rejected.refresh_from_db()
        validated.refresh_from_db()
        self.assertTrue(rejected.rejected)
        self.assertEqual((validated.validated, validated.confidence), (True, "alta"))
        # outra escola não vê nada disso
        other = School.objects.create(name="Outra", code="o")
        self.assertFalse(CurriculumItem.objects.filter(CurriculumItem.visible_q(other), code__startswith="CMDF-").exists())

    def test_suggestion_for_objective_that_repeats_the_skill(self):
        codes = {"CMDF-LP08-O012"}
        with mock.patch.object(df_curriculum, "dataset", return_value=_subset(codes)):
            df_curriculum.import_for_school(self.school, self.coord)
        c = CurriculumCorrespondence.objects.filter(source__code="CMDF-LP08-O012").order_by("-confidence").first()
        self.assertEqual((c.target.code, c.confidence, c.relation), ("EF08LP11", "media", "relacionada"))
        self.assertIn("Texto quase igual", c.rationale)


class CurationQueueTests(Base):
    def setUp(self):
        super().setUp()
        codes = {"CMDF-MA06-O001", "CMDF-MA06-O002", "CMDF-LP08-O012"}
        with mock.patch.object(df_curriculum, "dataset", return_value=_subset(codes)):
            df_curriculum.import_for_school(self.school, self.coord)
        self.mine = CurriculumCorrespondence.objects.filter(school=self.school)
        self.url = reverse("curriculum:curation")

    def test_queue_filters_orders_and_decides_in_bulk(self):
        self.assertGreaterEqual(self.mine.count(), 3)
        self.login(self.prof)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.login(self.coord)
        r = self.client.get(self.url)
        rows = list(r.context["rows"])
        self.assertEqual(rows[0].confidence, "media")  # a mais confiável primeiro
        self.assertContains(r, "EF08LP11")
        r = self.client.get(self.url, {"componente": "Matemática", "ano": "6"})
        self.assertTrue(all(c.source.component == "Matemática" for c in r.context["rows"]))
        self.assertNotContains(r, "EF08LP11")
        # outra escola e correspondências nacionais (BNCC → PNED) ficam fora da decisão em lote
        other = School.objects.create(name="Outra", code="o")
        foreign = CurriculumCorrespondence.objects.create(school=other, source=rows[0].source, target=self.h1,
                                                          origin="manual")
        national = CurriculumCorrespondence.objects.filter(school__isnull=True, validated=False).first()
        ids = [c.pk for c in rows[:2]] + [foreign.pk, national.pk]
        r = self.client.post(self.url, {"ids": ids, "decisao": "validar", "relacao": "equivalente",
                                        "voltar": "componente=Matem%C3%A1tica&ano=6&x=y"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("ano=6", r["Location"])
        self.assertNotIn("x=y", r["Location"])
        self.assertEqual(self.mine.filter(validated=True, validated_by=self.coord, relation="equivalente").count(), 2)
        foreign.refresh_from_db()
        national.refresh_from_db()
        self.assertFalse(foreign.validated or national.validated)
        self.assertTrue(AuditLog.objects.filter(target_id="lote", detail__startswith="Validou 2").exists())
        rest = self.mine.filter(validated=False).values_list("pk", flat=True)
        self.client.post(self.url, {"ids": list(rest), "decisao": "rejeitar"})
        self.assertFalse(self.mine.filter(validated=False, rejected=False).exists())
        self.assertContains(self.client.get(self.url), "Nada aguardando decisão")


class ScreenTests(Base):
    def setUp(self):
        super().setUp()
        self.codes = {"CMDF-MA06-O001", "CMDF-MA06-O002", "CMDF-MA06-C001"}
        patcher = mock.patch.object(df_curriculum, "dataset", return_value=_subset(self.codes))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_coordination_imports_from_screen(self):
        url = reverse("curriculum:item_import")
        self.login(self.prof)
        self.assertEqual(self.client.post(url, {"acao": "curriculo_df"}).status_code, 403)
        self.login(self.coord)
        self.assertContains(self.client.get(url), "Importar o Currículo em Movimento")
        r = self.client.post(url, {"acao": "curriculo_df"}, follow=True)
        self.assertContains(r, "3 itens novos")
        self.assertContains(r, "Atualizar o Currículo em Movimento")
        self.assertContains(r, "3 itens já na escola")
        self.assertEqual(CurriculumItem.objects.filter(school=self.school, code__in=self.codes).count(), 3)
        self.assertTrue(AuditLog.objects.filter(action="import", target_id="curriculo_df").exists())

    def test_teacher_picker_separates_sources_bncc_first(self):
        from apps.curriculum.services import picker_groups

        df_curriculum.import_for_school(self.school, self.coord)
        groups = picker_groups(self.prof)
        labels = [label for label, _ in groups]
        bncc = labels.index("Matemática — 6º ano")
        self.assertLess(bncc, labels.index("Matemática — 6º ano · Currículo em Movimento: objetivos"))
        self.assertLess(labels.index("Matemática — 6º ano · Currículo em Movimento: objetivos"),
                        labels.index("Matemática — 6º ano · Currículo em Movimento: conteúdos"))
        g = dict(groups)
        self.assertEqual({i.kind for i in g["Matemática — 6º ano"]}, {"habilidade"})
        self.assertEqual([i.code for i in g["Matemática — 6º ano · Currículo em Movimento: objetivos"]],
                         ["CMDF-MA06-O001", "CMDF-MA06-O002"])

    def test_review_filters_and_text_check(self):
        df_curriculum.import_for_school(self.school, self.coord)
        item = CurriculumItem.objects.get(code="CMDF-MA06-O001")
        self.login(self.coord)
        cat = reverse("curriculum:catalog")
        r = self.client.get(cat, {"situacao": "a_conferir"})
        self.assertContains(r, "CMDF-MA06-O001")
        self.assertNotContains(r, "EF06MA01")
        r = self.client.get(reverse("curriculum:item_detail", args=[item.pk]))
        self.assertContains(r, "Marcar como conferido")
        curate = reverse("curriculum:item_curate", args=[item.pk])
        old = item.text
        self.client.post(curate, {"acao": "conferir_texto", "texto": old + " (corrigido)"})
        item.refresh_from_db()
        self.assertFalse(item.needs_review)
        self.assertTrue(item.text.endswith("(corrigido)"))
        self.assertEqual(item.verified_on, self.today)
        self.assertEqual(CurriculumItemVersion.objects.get(item=item).text, old)
        self.assertNotContains(self.client.get(cat, {"situacao": "a_conferir"}), "CMDF-MA06-O001")
        # o texto da BNCC nacional não é editável por essa ação; professor não confere
        r = self.client.post(reverse("curriculum:item_curate", args=[self.h1.pk]), {"acao": "conferir_texto", "texto": "x"})
        self.assertEqual(r.status_code, 403)
        self.login(self.prof)
        other = CurriculumItem.objects.get(code="CMDF-MA06-O002")
        r = self.client.post(reverse("curriculum:item_curate", args=[other.pk]), {"acao": "conferir_texto", "texto": "x"})
        self.assertEqual(r.status_code, 403)
        self.assertNotContains(self.client.get(cat), "Situação")
