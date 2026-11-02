"""Glossário da ajuda (Prompt 9 §8.11): por perfil e conferido com as regras."""

from django.test import TestCase
from django.urls import reverse

from apps.core.models import Role, School, User


class HelpGlossaryTests(TestCase):
    def setUp(self):
        school = School.objects.create(name="Escola", code="e")
        for name, role in (("resp", Role.RESPONSAVEL), ("prof", Role.PROFESSOR), ("aluna", Role.ESTUDANTE)):
            User.objects.create_user(name, password="senha-forte-1", role=role, school=school)

    def glossary(self, user):
        self.client.login(username=user, password="senha-forte-1")
        resp = self.client.get(reverse("help"))
        self.assertEqual(resp.status_code, 200)
        return {g["term"] for g in resp.context["glossary"]}

    def test_glossary_by_role(self):
        prof, resp, aluna = self.glossary("prof"), self.glossary("resp"), self.glossary("aluna")
        self.assertIn("Cobertura de registro", prof)       # termo da equipe
        self.assertNotIn("Cobertura de registro", resp)
        self.assertIn("Entrega registrada e “Estou ciente”", resp)
        self.assertNotIn("Ocorrência", aluna)               # o estudante não vê ocorrências
        self.assertIn("Frequência", aluna)

    def test_glossary_matches_the_code(self):
        """As regras citadas no texto são as do código."""
        from apps.analytics.bi import SMALL_GROUP
        from apps.core.help import GLOSSARY
        from apps.pedagogy.models import InterventionPlan

        texts = {t: d for t, d, _ in GLOSSARY}
        self.assertIn(f"menos de {SMALL_GROUP} estudantes", texts["Grupo pequeno"])
        self.assertIn(f"mais de {InterventionPlan.STALE_DAYS} dias", texts["Plano de acompanhamento"])
