"""Validade de conteúdo da prova: o blueprint declarado × o que as questões medem."""

from decimal import Decimal

from django.urls import reverse

from apps.cognitio.blueprint import blueprint_check
from apps.cognitio.models import Question, QuestionSkill
from apps.cognitio.tests.test_evidence import Base


class BlueprintServiceTests(Base):
    def _question(self, number, main, points="2", secondary=None, declare=True):
        q = Question.objects.create(evaluation=self.ev, number=number, label=f"Q{number}",
                                    max_points=Decimal(points))
        QuestionSkill.objects.create(question=q, item=main, role=QuestionSkill.Role.MAIN)
        if secondary is not None:
            QuestionSkill.objects.create(question=q, item=secondary, role=QuestionSkill.Role.SECONDARY)
        if declare:
            extra = [secondary] if secondary is not None else []
            self.ev.curriculum.add(main, *extra)
        return q

    def test_empty_has_no_data(self):
        self.assertFalse(blueprint_check(self.ev)["has_data"])

    def test_weighting_per_declared_skill(self):
        self._question(1, self.h1, points="2")
        self._question(2, self.h1, points="4")  # mesma habilidade em 2 questões, 6 pontos
        data = blueprint_check(self.ev)
        self.assertTrue(data["has_data"])
        self.assertEqual(data["n_questions"], 2)
        self.assertEqual(data["total_points"], Decimal("6"))
        row = next(r for r in data["rows"] if r["item"] == self.h1)
        self.assertEqual((row["questions"], row["points"], row["measured"], row["declared"], row["principal"]),
                         (2, Decimal("6"), True, True, True))
        self.assertEqual(row["share"], Decimal("100"))
        self.assertEqual(data["aligned"], 1)
        self.assertEqual(data["not_measured"], [])
        self.assertEqual(data["not_declared"], [])

    def test_declared_but_not_measured(self):
        self._question(1, self.h1)
        self.ev.curriculum.add(self.h2)  # declarada na avaliação, nenhuma questão a mede
        data = blueprint_check(self.ev)
        self.assertEqual([r["item"] for r in data["not_measured"]], [self.h2])
        self.assertEqual(data["aligned"], 1)

    def test_measured_but_not_declared(self):
        self._question(1, self.h1, declare=False)  # mede h1, mas fora do blueprint
        self.ev.curriculum.clear()
        data = blueprint_check(self.ev)
        self.assertEqual([r["item"] for r in data["not_declared"]], [self.h1])
        self.assertEqual(data["aligned"], 0)

    def test_share_sums_over_100_with_overlap(self):
        # Uma questão que mede duas habilidades: cada uma recebe os pontos inteiros da questão.
        self._question(1, self.h1, points="2", secondary=self.h2)
        data = blueprint_check(self.ev)
        shares = {r["item"]: r["share"] for r in data["rows"]}
        self.assertEqual(shares[self.h1], Decimal("100"))
        self.assertEqual(shares[self.h2], Decimal("100"))


class BlueprintViewTests(Base):
    def test_panel_lists_unmeasured_declared_skill(self):
        q = Question.objects.create(evaluation=self.ev, number=1, label="Q1", max_points=Decimal("2"))
        QuestionSkill.objects.create(question=q, item=self.h1, role=QuestionSkill.Role.MAIN)
        self.ev.curriculum.add(self.h1, self.h2)  # h2 declarada sem questão
        self.login(self.prof)
        r = self.client.get(reverse("cognitio:questions", args=[self.ev.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Validade de conteúdo")
        self.assertContains(r, self.h2.code)

    def test_other_teacher_denied(self):
        self.login(self.prof_b)
        self.assertEqual(self.client.get(reverse("cognitio:questions", args=[self.ev.pk])).status_code, 403)
