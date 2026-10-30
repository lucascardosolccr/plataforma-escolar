"""Busca global (Ctrl+K): ninguém encontra quem não poderia abrir.

A busca devolve nomes de estudantes, que são dados de menores. Ela usa a
mesma regra da lista de estudantes (``students_visible_to``) e a do painel da
turma; estes testes garantem que nenhum perfil enxerga além disso.
"""

from django.test import TestCase
from django.urls import reverse

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.core.models import Role, School, User
from apps.registry.models import Enrollment, GuardianLink, Student

PW = "senha-forte-1"


class GlobalSearchTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola A", code="a")
        self.other = School.objects.create(name="Escola B", code="b")
        year = SchoolYear.objects.create(school=self.school, name="2026")
        self.t1 = ClassGroup.objects.create(school=self.school, school_year=year, name="5º Ano A")
        self.t2 = ClassGroup.objects.create(school=self.school, school_year=year, name="5º Ano B")
        mat = Subject.objects.create(school=self.school, name="Matemática")

        def mk(username, role, school=None):
            return User.objects.create_user(
                username=username, password=PW, role=role, school=school or self.school
            )

        self.sec = mk("sec", Role.SECRETARIA)
        self.prof = mk("prof", Role.PROFESSOR)
        self.resp = mk("resp", Role.RESPONSAVEL)
        self.aluno_conta = mk("aluno", Role.ESTUDANTE)
        self.sec_b = mk("sec_b", Role.SECRETARIA, self.other)
        TeacherAssignment.objects.create(
            school=self.school, school_year=year, teacher=self.prof,
            class_group=self.t1, subject=mat,
        )
        # Duas homônimas em turmas diferentes e uma estudante de outra escola.
        self.alice_a = Student.objects.create(school=self.school, first_name="Alice", last_name="Almeida")
        self.alice_b = Student.objects.create(school=self.school, first_name="Alice", last_name="Almeida")
        self.bruno = Student.objects.create(school=self.school, first_name="Bruno", last_name="Souza")
        self.alice_outra = Student.objects.create(school=self.other, first_name="Alice", last_name="Lima")
        Enrollment.objects.create(school=self.school, student=self.alice_a, class_group=self.t1, school_year=year)
        Enrollment.objects.create(school=self.school, student=self.alice_b, class_group=self.t2, school_year=year)
        Enrollment.objects.create(school=self.school, student=self.bruno, class_group=self.t1, school_year=year)
        GuardianLink.objects.create(school=self.school, guardian=self.resp, student=self.bruno, status="aprovado")
        GuardianLink.objects.create(school=self.school, guardian=self.resp, student=self.alice_a, status="pendente")
        self.alice_a.user = self.aluno_conta
        self.alice_a.save(update_fields=["user"])

    def search(self, username, q):
        self.client.logout()
        self.assertTrue(self.client.login(username=username, password=PW))
        resp = self.client.get(reverse("global_search"), {"q": q})
        self.assertEqual(resp.status_code, 200)
        return resp.json()["results"]

    def urls(self, results, group):
        return {r["url"] for r in results if r["group"] == group}

    def test_anonymous_cannot_search(self):
        resp = self.client.get(reverse("global_search"), {"q": "Alice"})
        self.assertEqual(resp.status_code, 302)

    def test_short_query_returns_nothing(self):
        self.assertEqual(self.search("sec", "a"), [])

    def test_staff_sees_own_school_only(self):
        res = self.search("sec", "Alice")
        urls = self.urls(res, "Estudantes")
        self.assertIn(reverse("student_detail", args=[self.alice_a.pk]), urls)
        self.assertIn(reverse("student_detail", args=[self.alice_b.pk]), urls)
        self.assertNotIn(reverse("student_detail", args=[self.alice_outra.pk]), urls)
        self.assertEqual(self.search("sec_b", "Almeida"), [])

    def test_homonyms_are_told_apart_by_class(self):
        hints = sorted(r["hint"] for r in self.search("sec", "Alice Almeida"))
        self.assertEqual(hints, ["Turma 5º Ano A", "Turma 5º Ano B"])

    def test_teacher_sees_only_students_and_classes_he_teaches(self):
        res = self.search("prof", "Alice")
        self.assertEqual(
            self.urls(res, "Estudantes"), {reverse("student_detail", args=[self.alice_a.pk])}
        )
        turmas = self.urls(self.search("prof", "5º Ano"), "Turmas")
        self.assertEqual(turmas, {reverse("analytics:class_dashboard", args=[self.t1.pk])})

    def test_guardian_sees_only_approved_children(self):
        self.assertEqual(
            self.urls(self.search("resp", "Bruno"), "Estudantes"),
            {reverse("student_detail", args=[self.bruno.pk])},
        )
        # Vínculo pendente não dá acesso, nem pela busca.
        self.assertEqual(self.search("resp", "Alice"), [])
        # Responsável não abre painel de turma: turma não aparece.
        self.assertEqual(self.urls(self.search("resp", "5º Ano"), "Turmas"), set())

    def test_student_account_finds_no_records(self):
        self.assertEqual(self.search("aluno", "Bruno"), [])
        self.assertEqual(self.search("aluno", "Alice"), [])

    def test_every_result_opens_for_who_searched(self):
        for username, q in (("sec", "Alice"), ("prof", "Alice"), ("prof", "5º"), ("resp", "Bruno")):
            for r in self.search(username, q):
                with self.subTest(usuario=username, url=r["url"]):
                    self.assertEqual(self.client.get(r["url"]).status_code, 200)
