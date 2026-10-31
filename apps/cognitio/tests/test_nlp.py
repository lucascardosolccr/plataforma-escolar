"""PLN por regras: análise explicável, revisão humana e sugestão de habilidades (Prompt 16, etapa 8)."""

from django.urls import reverse

from apps.cognitio.models import AnalysisFeedback, SkillEvidence, TextAnalysis
from apps.cognitio.nlp import analyze, suggest_skills
from apps.cognitio.tests.test_evidence import Base
from apps.cognitio.views_text import analyzer_quality


class AnalyzerTests(Base):
    def test_spelling_does_not_change_the_analysis(self):
        right = "A cidade cresceu porque chegaram fábricas. Por isso o rio ficou poluído.\n\nAlém disso, o campo esvaziou."
        wrong = "A sidade cresseu porque chegaram fabricas. Por isso o rio ficou poluido.\n\nAlem disso, o canpo esvasiou."
        a, b = analyze(right, "Língua Portuguesa"), analyze(wrong, "Língua Portuguesa")
        self.assertEqual([(s["key"], s["status"]) for s in a["signals"]], [(s["key"], s["status"]) for s in b["signals"]])
        self.assertTrue(any("Ortografia" in n for n in a["notes"]))
        self.assertTrue(a["review_required"])
        self.assertNotIn("nota", a)
        self.assertIn(a["confidence"], ("baixa", "média"))

    def test_lenses_differ_by_component(self):
        math = analyze("12 x 3 = 36\n36 + 4 = 40\nResposta: 40 figurinhas", "Matemática")
        keys = {s["key"]: s["status"] for s in math["signals"]}
        self.assertEqual(keys["procedimento"], "evidenciado")
        self.assertEqual(keys["justificativa"], "nao_evidenciado")
        sci = analyze("Observamos que a planta no escuro murchou porque não recebeu luz.", "Ciências",
                      expected_concepts="luz, fotossíntese")
        k2 = {s["key"]: s for s in sci["signals"]}
        self.assertEqual(k2["evidencia"]["status"], "evidenciado")
        self.assertIn("Observamos", k2["evidencia"]["excerpt"])
        self.assertEqual(k2["conceito:fotossintese"]["status"], "nao_evidenciado")
        hist = analyze("No século XIX os trabalhadores imigrantes chegaram, segundo cartas da época.", "História")
        self.assertEqual({s["key"] for s in hist["signals"]}, {"tempo", "sujeitos", "fontes"})

    def test_skill_suggestion_uses_official_text(self):
        res = suggest_skills("Frações equivalentes: comparar e ordenar frações de inteiros", self.school, "Matemática", 6)
        self.assertIn("EF06MA07", [r["item"].code for r in res])
        self.assertEqual(suggest_skills("qualquer", self.school, "", 6), [])


class TextFlowTests(Base):
    def test_create_review_and_evidence_only_after_review(self):
        self.login(self.prof)
        r = self.client.post(reverse("cognitio:text_create"), {
            "pair": f"{self.cg.pk}:{self.mat.pk}", "student": self.ana.pk, "title": "Resposta Q3",
            "prompt_text": "Explique como comparou as frações", "text": "Comparei 1/2 e 2/4 = iguais porque dobrei.",
            "expected_concepts": "equivalentes", "skill_codes": "EF06MA07", "produced_on": self.today.isoformat()})
        self.assertEqual(r.status_code, 302)
        t = TextAnalysis.objects.get()
        self.assertEqual(t.engine_version, "regras-1.0")
        self.assertFalse(SkillEvidence.objects.filter(source_type="texto").exists())
        url = reverse("cognitio:text_detail", args=[t.pk])
        key = t.result["signals"][0]["key"]
        self.client.post(url, {"acao": "sinal", "sinal": key, "concorda": "0"})
        self.assertFalse(AnalysisFeedback.objects.get().agrees)
        self.client.post(url, {"acao": "revisar", "nivel": "3", "devolutiva": "Explique a equivalência.",
                               "habilidades": "EF06MA07"})
        from apps.cognitio.evidence import rebuild_class

        rebuild_class(self.cg)
        e = SkillEvidence.objects.get(source_type="texto")
        self.assertEqual((e.item.code, e.weight, e.ratio), ("EF06MA07", 0.8, 0.55))
        self.assertEqual(analyzer_quality(self.school)[0][1:], (1, 0, 0))
        self.login(self.prof_b)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.login(self.coord)
        r = self.client.get(url)
        self.assertNotContains(r, "Sua revisão")  # coordenação lê; quem revisa é o professor da turma

    def test_student_must_belong_to_the_class(self):
        self.login(self.prof)
        from apps.registry.models import Student

        other = Student.objects.create(school=self.school, first_name="Fora")
        r = self.client.post(reverse("cognitio:text_create"), {
            "pair": f"{self.cg.pk}:{self.mat.pk}", "student": other.pk, "title": "x", "text": "y",
            "produced_on": self.today.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(TextAnalysis.objects.exists())
