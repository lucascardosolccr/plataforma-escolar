"""Identificador malformado na URL não derruba a página.

Antes, ``?estudante=abc`` virava erro 500 em nove listagens: o valor ia
direto para ``filter(pk=...)``.
"""

from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from apps.core.params import id_param

from .test_pedagogy import PedagogyBase

URLS = [
    ("pedagogy:activity_list", "?turma=abc&disciplina=x&estudante=zz&de=nope"),
    ("pedagogy:group_work_list", "?turma=abc&disciplina=x&estudante=zz"),
    ("pedagogy:evaluation_list", "?estudante=abc"),
    ("pedagogy:attendance_list", "?estudante=abc"),
    ("pedagogy:occurrence_list", "?estudante=abc"),
    ("pedagogy:observation_list", "?estudante=abc"),
    ("pedagogy:plan_list", "?estudante=abc"),
    ("pedagogy:justification_list", "?estudante=abc"),
    ("enrollment_list", "?year=abc"),
    ("communication:thread_list", "?estudante=abc"),
    ("communication:announcement_list", "?estudante=abc"),
]


class MalformedParamTests(PedagogyBase):
    def test_no_server_error_for_any_profile(self):
        for username in ("sec", "coord", "prof", "resp", "adm"):
            self.login(username)
            for name, query in URLS:
                with self.subTest(perfil=username, url=name):
                    resp = self.client.get(reverse(name) + query)
                    self.assertLess(resp.status_code, 500)

    def test_valid_id_still_filters(self):
        self.login("coord")
        resp = self.client.get(
            reverse("pedagogy:activity_list") + f"?turma={self.turma.pk}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["class_filter"], str(self.turma.pk))


class IdParamTests(SimpleTestCase):
    def test_accepts_only_positive_ascii_integers(self):
        rf = RequestFactory()
        casos = {"7": "7", " 12 ": "12", "abc": None, "-1": None, "0": None,
                 "1e3": None, "٣": None, "": None}
        for bruto, esperado in casos.items():
            with self.subTest(bruto=bruto):
                req = rf.get("/", {"x": bruto})
                self.assertEqual(id_param(req, "x"), esperado)
