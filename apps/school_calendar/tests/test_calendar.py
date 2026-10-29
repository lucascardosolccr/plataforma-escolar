from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.core.models import Role, School
from apps.pedagogy.models import (
    AbsenceJustification,
    Activity,
    Evaluation,
    GroupWork,
    Occurrence,
)
from apps.registry.models import Enrollment, GuardianLink, Student

User = get_user_model()


class CalendarBase(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.school = School.objects.create(name="Escola A", code="a")
        self.school_b = School.objects.create(name="Escola B", code="b")
        pw = "senha-forte-1"
        self.prof = User.objects.create_user(
            username="prof", password=pw, role=Role.PROFESSOR, school=self.school
        )
        self.prof2 = User.objects.create_user(
            username="prof2", password=pw, role=Role.PROFESSOR, school=self.school
        )
        self.resp = User.objects.create_user(
            username="resp", password=pw, role=Role.RESPONSAVEL, school=self.school
        )
        self.other_resp = User.objects.create_user(
            username="outro", password=pw, role=Role.RESPONSAVEL, school=self.school
        )
        self.secretaria = User.objects.create_user(
            username="sec", password=pw, role=Role.SECRETARIA, school=self.school
        )
        self.year = SchoolYear.objects.create(school=self.school, name="2026")
        self.turma = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="1º Ano A"
        )
        self.turma_b = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="1º Ano B"
        )
        self.mat = Subject.objects.create(school=self.school, name="Matemática")
        self.port = Subject.objects.create(school=self.school, name="Português")
        TeacherAssignment.objects.create(
            school=self.school,
            school_year=self.year,
            teacher=self.prof,
            class_group=self.turma,
            subject=self.mat,
        )
        TeacherAssignment.objects.create(
            school=self.school,
            school_year=self.year,
            teacher=self.prof2,
            class_group=self.turma_b,
            subject=self.port,
        )
        self.ana = Student.objects.create(school=self.school, first_name="Ana")
        self.bea = Student.objects.create(school=self.school, first_name="Beatriz")
        self.caio = Student.objects.create(school=self.school, first_name="Caio")
        Enrollment.objects.create(
            school=self.school,
            student=self.ana,
            class_group=self.turma,
            school_year=self.year,
        )
        Enrollment.objects.create(
            school=self.school,
            student=self.bea,
            class_group=self.turma,
            school_year=self.year,
        )
        Enrollment.objects.create(
            school=self.school,
            student=self.caio,
            class_group=self.turma_b,
            school_year=self.year,
        )
        GuardianLink.objects.create(
            school=self.school, guardian=self.resp, student=self.ana, status="aprovado"
        )
        GuardianLink.objects.create(
            school=self.school, guardian=self.resp, student=self.bea, status="aprovado"
        )
        GuardianLink.objects.create(
            school=self.school,
            guardian=self.other_resp,
            student=self.caio,
            status="aprovado",
        )

    def login(self, username):
        self.client.login(username=username, password="senha-forte-1")

    def make_activity(self, **kwargs):
        data = {
            "school": self.school,
            "class_group": self.turma,
            "subject": self.mat,
            "title": "Atividade de frações",
            "description": "Resolver as questões 1 a 5.",
            "published_date": self.today,
            "deadline": self.today + timedelta(days=2),
            "status": Activity.Status.PUBLISHED,
            "created_by": self.prof,
        }
        data.update(kwargs)
        return Activity.objects.create(**data)

    def make_evaluation(self, **kwargs):
        data = {
            "school": self.school,
            "class_group": self.turma,
            "subject": self.mat,
            "title": "Prova de frações",
            "date": self.today,
            "status": Evaluation.Status.PUBLISHED,
            "created_by": self.prof,
        }
        data.update(kwargs)
        return Evaluation.objects.create(**data)

    def make_group_work(self, **kwargs):
        data = {
            "school": self.school,
            "class_group": self.turma,
            "subject": self.mat,
            "title": "Maquete do sistema solar",
            "description": "Montar em grupo.",
            "published_date": self.today,
            "deadline": self.today + timedelta(days=5),
            "status": GroupWork.Status.PUBLISHED,
            "created_by": self.prof,
        }
        data.update(kwargs)
        return GroupWork.objects.create(**data)

    def calendar(self, **params):
        return self.client.get(reverse("school_calendar:calendar_index"), params)


class CalendarAccessTests(CalendarBase):
    def test_anonymous_goes_to_login(self):
        response = self.client.get(reverse("school_calendar:calendar_index"))
        self.assertEqual(response.status_code, 302)

    def test_professor_sees_own_class_only(self):
        self.make_activity(title="Atividade da turma A")
        self.make_activity(
            title="Atividade da turma B",
            class_group=self.turma_b,
            subject=self.port,
            created_by=self.prof2,
        )
        self.login("prof")
        response = self.calendar()
        self.assertContains(response, "Atividade da turma A")
        self.assertNotContains(response, "Atividade da turma B")

    def test_professor_does_not_see_other_class_evaluation(self):
        self.make_evaluation(title="Prova da turma A")
        self.make_evaluation(
            title="Prova da turma B",
            class_group=self.turma_b,
            subject=self.port,
            created_by=self.prof2,
        )
        self.login("prof")
        response = self.calendar()
        self.assertContains(response, "Prova da turma A")
        self.assertNotContains(response, "Prova da turma B")

    def test_family_sees_published_activity_and_child_name(self):
        self.make_activity()
        self.login("resp")
        response = self.calendar()
        self.assertContains(response, "Atividade de frações")
        self.assertContains(response, "Ana")
        self.assertContains(response, "Beatriz")

    def test_family_does_not_see_draft_or_future_publication(self):
        self.make_activity(title="Rascunho", status=Activity.Status.DRAFT)
        self.make_activity(
            title="Publicação futura", published_date=self.today + timedelta(days=3)
        )
        self.login("resp")
        response = self.calendar()
        self.assertNotContains(response, "Rascunho")
        self.assertNotContains(response, "Publicação futura")

    def test_family_does_not_see_other_class(self):
        self.make_activity(
            title="Atividade de outra turma",
            class_group=self.turma_b,
            subject=self.port,
            created_by=self.prof2,
        )
        self.login("resp")
        response = self.calendar()
        self.assertNotContains(response, "Atividade de outra turma")

    def test_family_evaluation_does_not_break(self):
        self.make_evaluation(title="Prova publicada")
        self.make_evaluation(
            title="Prova em rascunho", status=Evaluation.Status.DRAFT
        )
        self.login("resp")
        response = self.calendar(type="evaluation")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Prova publicada")
        self.assertNotContains(response, "Prova em rascunho")

    def test_family_canceled_activity_stays_in_history(self):
        self.make_activity(
            title="Atividade cancelada", status=Activity.Status.CANCELED
        )
        self.login("resp")
        response = self.calendar()
        self.assertContains(response, "Atividade cancelada")
        self.assertContains(response, "Cancelada")

    def test_guardian_cannot_filter_other_students_student(self):
        self.login("outro")
        response = self.calendar(student=self.ana.pk)
        self.assertEqual(response.status_code, 403)

    def test_guardian_filtering_own_child_shows_only_that_child(self):
        self.make_activity(title="Atividade da turma")
        self.login("resp")
        response = self.calendar(student=self.ana.pk)
        self.assertContains(response, "Atividade da turma")
        self.assertContains(response, "· Ana")
        self.assertNotContains(response, "· Beatriz")

    def test_professor_filtering_by_student_keeps_the_activity(self):
        self.make_activity(title="Atividade da turma")
        self.login("prof")
        response = self.calendar(student=self.ana.pk)
        self.assertContains(response, "Atividade da turma")
        self.assertContains(response, "· Ana")
        self.assertNotContains(response, "· Beatriz")

    def test_secretaria_filtering_by_student_keeps_the_activity(self):
        self.make_activity(title="Atividade da turma")
        self.login("sec")
        response = self.calendar(student=self.ana.pk)
        self.assertContains(response, "Atividade da turma")
        self.assertContains(response, "· Ana")

    def test_guardian_cannot_see_other_students_occurrence(self):
        Occurrence.objects.create(
            school=self.school,
            student=self.caio,
            description="Ocorrência confidencial",
            date=self.today,
        )
        self.login("resp")
        response = self.calendar()
        self.assertNotContains(response, "Ocorrência confidencial")

    def test_guardian_sees_own_child_occurrence(self):
        Occurrence.objects.create(
            school=self.school,
            student=self.ana,
            description="Ocorrência da Ana",
            date=self.today,
        )
        self.login("resp")
        response = self.calendar()
        self.assertContains(response, "Ocorrência da Ana")

    def test_secretaria_sees_school_events_and_students(self):
        self.make_activity()
        self.login("sec")
        response = self.calendar()
        self.assertContains(response, "Atividade de frações")
        self.assertContains(response, "Caio")

    def test_cross_school_class_filter_is_not_found(self):
        turma_b = ClassGroup.objects.create(
            school=self.school_b, school_year=self.year, name="Turma da outra escola"
        )
        self.login("sec")
        response = self.calendar(**{"class": turma_b.pk})
        self.assertEqual(response.status_code, 404)


class CalendarPeriodTests(CalendarBase):
    def test_period_includes_justification_that_overlaps(self):
        AbsenceJustification.objects.create(
            school=self.school,
            student=self.ana,
            class_group=self.turma,
            start_date=self.today - timedelta(days=5),
            end_date=self.today + timedelta(days=1),
            reason="Consulta médica",
        )
        self.login("resp")
        response = self.calendar(
            type="justification", start=self.today.isoformat()
        )
        self.assertContains(response, "Consulta médica")

    def test_period_excludes_event_outside_the_window(self):
        self.make_activity(
            title="Atividade antiga",
            published_date=self.today - timedelta(days=30),
            deadline=self.today - timedelta(days=20),
        )
        self.login("sec")
        response = self.calendar(start=self.today.isoformat())
        self.assertNotContains(response, "Atividade antiga")

    def test_invalid_kind_filter_is_ignored(self):
        self.make_activity()
        self.login("resp")
        response = self.calendar(type="../../etc/passwd")
        self.assertContains(response, "Atividade de frações")

    def test_invalid_date_is_ignored(self):
        self.make_activity()
        self.login("resp")
        response = self.calendar(start="não-é-data")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Atividade de frações")


class CalendarLinkTests(CalendarBase):
    def test_activity_link_opens_for_the_family(self):
        act = self.make_activity()
        self.login("resp")
        response = self.calendar()
        self.assertContains(
            response, reverse("pedagogy:activity_detail", args=[act.pk])
        )

    def test_group_work_link_opens_for_the_family(self):
        gw = self.make_group_work()
        self.login("resp")
        response = self.calendar()
        self.assertContains(
            response, reverse("pedagogy:group_work_detail", args=[gw.pk])
        )

    def test_evaluation_link_points_to_the_existing_list(self):
        self.make_evaluation()
        self.login("resp")
        response = self.calendar(type="evaluation")
        self.assertContains(response, reverse("pedagogy:evaluation_list"))

    def test_justification_does_not_link_to_a_missing_detail_page(self):
        AbsenceJustification.objects.create(
            school=self.school,
            student=self.ana,
            class_group=self.turma,
            start_date=self.today,
            end_date=self.today,
            reason="Atestado",
        )
        self.login("resp")
        response = self.calendar(type="justification")
        self.assertNotContains(response, "/justificativas/1/")

    def test_no_template_syntax_leaks(self):
        self.make_activity()
        self.login("resp")
        response = self.calendar()
        self.assertNotContains(response, "{%")


class CalendarPerformanceTests(CalendarBase):
    def _queries(self):
        with CaptureQueriesContext(connection) as ctx:
            self.calendar()
        return len(ctx)

    def test_family_query_count_does_not_grow_per_activity(self):
        self.make_activity(title="Atividade única")
        self.login("resp")
        with_one = self._queries()
        for i in range(25):
            self.make_activity(title=f"Atividade extra {i}")
        with_many = self._queries()
        self.assertLessEqual(with_many, with_one + 2)

    def test_teacher_query_count_does_not_grow_per_activity(self):
        self.make_activity(title="Atividade única")
        self.login("prof")
        with_one = self._queries()
        for i in range(25):
            self.make_activity(title=f"Atividade extra {i}")
        with_many = self._queries()
        self.assertLessEqual(with_many, with_one + 2)
