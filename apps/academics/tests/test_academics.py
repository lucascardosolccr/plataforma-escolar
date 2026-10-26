from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.core.models import Role, School
from apps.registry.models import Enrollment, Student

User = get_user_model()


class AcademicsBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola A", code="a")
        self.school_b = School.objects.create(name="Escola B", code="b")
        self.secretaria = User.objects.create_user(
            username="sec", password="senha-forte-1", role=Role.SECRETARIA, school=self.school
        )
        self.prof = User.objects.create_user(
            username="prof", password="senha-forte-1", role=Role.PROFESSOR, school=self.school
        )
        self.resp = User.objects.create_user(
            username="resp", password="senha-forte-1", role=Role.RESPONSAVEL, school=self.school
        )
        self.year = SchoolYear.objects.create(school=self.school, name="2026")

    def login(self, username):
        self.client.login(username=username, password="senha-forte-1")


class AcademicsCrudTests(AcademicsBase):
    def test_create_school_year_marks_current(self):
        self.login("sec")
        self.client.post(
            "/anos-letivos/novo/",
            {"name": "2027", "start_date": "2027-02-01", "end_date": "2027-12-15", "is_current": "on"},
            follow=True,
        )
        y = SchoolYear.objects.get(name="2027")
        self.assertTrue(y.is_current)
        self.year.refresh_from_db()
        self.assertFalse(self.year.is_current)

    def test_duplicate_school_year_rejected(self):
        self.login("sec")
        resp = self.client.post("/anos-letivos/novo/", {"name": "2026"})
        self.assertContains(resp, "Já existe um ano letivo")

    def test_duplicate_turma_rejected(self):
        ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="1º Ano A"
        )
        self.login("sec")
        resp = self.client.post(
            "/turmas/nova/",
            {"school_year": self.year.pk, "name": "1º Ano A", "turn": "manha"},
        )
        self.assertContains(resp, "Já existe uma turma")

    def test_duplicate_subject_rejected(self):
        Subject.objects.create(school=self.school, name="Matemática")
        self.login("sec")
        resp = self.client.post("/disciplinas/nova/", {"name": "Matemática"})
        self.assertContains(resp, "Já existe uma disciplina")

    def test_duplicate_assignment_rejected(self):
        subj = Subject.objects.create(school=self.school, name="Língua Portuguesa")
        turma = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="2º Ano A"
        )
        TeacherAssignment.objects.create(
            school=self.school,
            school_year=self.year,
            teacher=self.prof,
            class_group=turma,
            subject=subj,
        )
        self.login("sec")
        resp = self.client.post(
            "/atribuicoes/nova/",
            {
                "teacher": self.prof.pk,
                "class_group": turma.pk,
                "subject": subj.pk,
                "school_year": self.year.pk,
            },
        )
        self.assertContains(resp, "já está atribuído")

    def test_assignment_with_other_school_rejected(self):
        year_b = SchoolYear.objects.create(school=self.school_b, name="2026")
        subj = Subject.objects.create(school=self.school, name="História")
        turma = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="3º Ano A"
        )
        self.login("sec")
        resp = self.client.post(
            "/atribuicoes/nova/",
            {
                "teacher": self.prof.pk,
                "class_group": turma.pk,
                "subject": subj.pk,
                "school_year": year_b.pk,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            TeacherAssignment.objects.filter(school_year=year_b).exists()
        )


class AcademicsAccessTests(AcademicsBase):
    def test_teacher_only_role_cannot_manage(self):
        self.login("prof")
        self.assertEqual(self.client.get("/turmas/nova/").status_code, 403)
        self.assertEqual(self.client.get("/disciplinas/nova/").status_code, 403)
        self.assertEqual(self.client.get("/anos-letivos/novo/").status_code, 403)

    def test_responsavel_blocked_from_academic_pages(self):
        self.login("resp")
        self.assertEqual(self.client.get("/turmas/").status_code, 403)
        self.assertEqual(self.client.get("/disciplinas/").status_code, 403)
        self.assertEqual(self.client.get("/anos-letivos/").status_code, 403)

    def test_secretaria_can_manage(self):
        self.login("sec")
        self.assertEqual(self.client.get("/turmas/nova/").status_code, 200)
        self.assertEqual(self.client.get("/disciplinas/nova/").status_code, 200)
        self.assertEqual(self.client.get("/atribuicoes/nova/").status_code, 200)
        self.assertEqual(self.client.get("/anos-letivos/").status_code, 200)

    def test_teacher_roster_only_own_turma(self):
        subj = Subject.objects.create(school=self.school, name="Ciências")
        turma_a = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="1º Ano A"
        )
        turma_b = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="1º Ano B"
        )
        ana = Student.objects.create(school=self.school, first_name="Ana")
        bea = Student.objects.create(school=self.school, first_name="Beatriz")
        TeacherAssignment.objects.create(
            school=self.school,
            school_year=self.year,
            teacher=self.prof,
            class_group=turma_a,
            subject=subj,
        )
        Enrollment.objects.create(
            school=self.school, student=ana, class_group=turma_a, school_year=self.year
        )
        Enrollment.objects.create(
            school=self.school, student=bea, class_group=turma_b, school_year=self.year
        )

        self.login("prof")
        resp = self.client.get("/minhas-turmas/")
        self.assertContains(resp, "Ana")
        self.assertNotContains(resp, "Beatriz")