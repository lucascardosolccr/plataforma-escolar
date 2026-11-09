"""Identificador malformado na URL não derruba a página.

Antes, ``?estudante=abc`` virava erro 500 em nove listagens: o valor ia
direto para ``filter(pk=...)``.
"""

from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from apps.core.params import as_id, as_uuid, digits, id_param, safe_next

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
                 "1e3": None, "٣": None, "": None, "²": None,
                 "99999999999999999999": None, str(2**63 - 1): str(2**63 - 1)}
        for bruto, esperado in casos.items():
            with self.subTest(bruto=bruto):
                req = rf.get("/", {"x": bruto})
                self.assertEqual(id_param(req, "x"), esperado)


    def test_digits_as_id_as_uuid(self):
        self.assertTrue(digits("0"))
        self.assertFalse(digits("²"))           # "²".isdigit() é True, mas int("²") levanta erro
        self.assertFalse(digits(str(2**63)))    # não cabe no SQLite
        self.assertEqual((as_id("12"), as_id("0"), as_id(None), as_id("abc")), (12, None, None, None))
        self.assertIsNone(as_uuid("abc"))
        self.assertEqual(str(as_uuid("12345678-1234-5678-1234-567812345678")), "12345678-1234-5678-1234-567812345678")

    def test_safe_next_only_paths_of_this_site(self):
        rf = RequestFactory()
        for bruto, esperado in {"/atividades/?p=2": "/atividades/?p=2", "abc": "padrao",
                                "99999999999999999999": "padrao", "//outro.site/x": "padrao",
                                "https://outro.site/": "padrao", "": "padrao"}.items():
            with self.subTest(bruto=bruto):  # "abc" virava nome de rota no redirect: NoReverseMatch, erro 500
                self.assertEqual(safe_next(rf.post("/", {"next": bruto}), "padrao"), esperado)


HUGE = "99999999999999999999"
#: Achados da varredura de 09/11/2026: número maior que o SQLite guarda (OverflowError) ou algarismo não latino
#: ("²" passa no isdigit e quebra no int) davam erro 500 nestas telas.
OVERFLOW = [
    "/planejamento/?turma=", "/diario/?turma=", "/avaliacoes/?disciplina=", "/atividades/?disciplina=",
    "/trabalhos/?disciplina=", "/biblioteca/?disciplina=", "/conteudos-da-prova/?turma=", "/reunioes/?estudante=",
    "/fotografias/pendentes/?turma=", "/cognitio/alertas/?turma=", "/apoio/orientacoes/?estudante=",
    "/matriculas/?year=", "/declaracoes/?estudante=", "/atividades/anteriores/?disciplina=",
    "/curriculo/evidencias/nova/?turma=", "/curriculo/?year=",
]


class HugeAndOddIdTests(PedagogyBase):
    def test_huge_or_non_latin_numbers_never_break_a_page(self):
        for username in ("dir", "coord", "sec", "prof"):
            self.login(username)
            for path in OVERFLOW:
                for value in (HUGE, "²"):
                    with self.subTest(perfil=username, url=path, valor=value):
                        self.assertLess(self.client.get(path + value).status_code, 500)

    def test_invalid_ids_in_lookups_are_404_not_500(self):
        self.login("prof")
        self.assertEqual(self.client.get(reverse("printing:create") + "?atividade=abc").status_code, 404)
        self.login("resp")
        url = reverse("inclusion:document_upload", args=[self.ana.pk])
        self.assertEqual(self.client.get(url + "?substitui=abc").status_code, 404)

    def test_multi_select_with_huge_id_is_a_validation_error(self):
        from django import forms

        from apps.registry.models import Student

        field = forms.ModelMultipleChoiceField(Student.objects.all())
        with self.assertRaises(forms.ValidationError):  # antes: OverflowError do SQLite, erro 500
            field.clean([HUGE])
        self.assertEqual(list(field.clean([str(self.ana.pk)])), [self.ana])
