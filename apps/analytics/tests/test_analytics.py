import codecs
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.academics.models import (
    ClassGroup,
    SchoolYear,
    Subject,
    TeacherAssignment,
)
from apps.core.models import Role, School
from apps.pedagogy.models import (
    AcademicRule,
    Activity,
    AttendanceRecord,
    Evaluation,
    Grade,
    Occurrence,
    PedagogicalObservation,
    Submission,
)
from apps.registry.models import Enrollment, GuardianLink, Student

from .. import charts, services

User = get_user_model()
PW = "senha-forte-1"


class AnalyticsBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola A", code="a")
        self.school_b = School.objects.create(name="Escola B", code="b")
        self.admin = self._user("adm", Role.ADMIN, self.school)
        self.sec = self._user("sec", Role.SECRETARIA, self.school)
        self.coord = self._user("coord", Role.COORDENACAO, self.school)
        self.direc = self._user("dir", Role.DIRECAO, self.school)
        self.prof = self._user("prof", Role.PROFESSOR, self.school)
        self.prof_b = self._user("prof_b", Role.PROFESSOR, self.school_b)
        self.resp = self._user("resp", Role.RESPONSAVEL, self.school)
        self.resp_b = self._user("resp_b", Role.RESPONSAVEL, self.school_b)

        self.year = SchoolYear.objects.create(school=self.school, name="2026")
        self.turma = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="1 Ano A"
        )
        self.turma_b = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="1 Ano B"
        )
        self.mat = Subject.objects.create(school=self.school, name="Matematica")
        TeacherAssignment.objects.create(
            school=self.school,
            school_year=self.year,
            teacher=self.prof,
            class_group=self.turma,
            subject=self.mat,
        )
        self.ana = Student.objects.create(school=self.school, first_name="Ana")
        self.bea = Student.objects.create(school=self.school, first_name="Beatriz")
        self.cross = Student.objects.create(school=self.school_b, first_name="Carla")
        Enrollment.objects.create(
            school=self.school,
            student=self.ana,
            class_group=self.turma,
            school_year=self.year,
        )
        Enrollment.objects.create(
            school=self.school,
            student=self.bea,
            class_group=self.turma_b,
            school_year=self.year,
        )
        GuardianLink.objects.create(
            school=self.school, guardian=self.resp, student=self.ana, status="aprovado"
        )

    def _user(self, username, role, school):
        return User.objects.create_user(
            username=username, password=PW, role=role, school=school
        )

    def login(self, username):
        self.client.login(username=username, password=PW)

    # -- helpers de dados ---------------------------------------------------
    def make_evaluation(self, student, value, status=Evaluation.Status.PUBLISHED, **kw):
        ev = Evaluation.objects.create(
            school=self.school,
            subject=kw.get("subject", self.mat),
            class_group=kw.get("class_group", self.turma),
            title=kw.get("title", "Prova"),
            status=status,
            date=kw.get("date", "2026-03-01"),
            created_by=self.prof,
        )
        Grade.objects.create(
            school=self.school, evaluation=ev, student=student, value=Decimal(str(value))
        )
        return ev

    def make_attendance(self, student, present, absent, class_group=None):
        cg = class_group or self.turma
        day = 1
        for _ in range(present):
            AttendanceRecord.objects.create(
                school=self.school,
                class_group=cg,
                student=student,
                date=f"2026-03-{day:02d}",
                status=AttendanceRecord.Status.PRESENT,
            )
            day += 1
        for _ in range(absent):
            AttendanceRecord.objects.create(
                school=self.school,
                class_group=cg,
                student=student,
                date=f"2026-03-{day:02d}",
                status=AttendanceRecord.Status.ABSENT,
            )
            day += 1


class ServiceTests(AnalyticsBase):
    def test_subject_average_uses_published_only(self):
        self.make_evaluation(self.ana, 8)
        self.make_evaluation(self.ana, 6)
        self.make_evaluation(self.ana, 1, status=Evaluation.Status.DRAFT)
        averages = services.subject_averages(self.ana)
        self.assertEqual(len(averages), 1)
        self.assertEqual(averages[0]["average"], 7.0)
        self.assertFalse(averages[0]["below"])

    def test_subject_average_marks_below_passing(self):
        AcademicRule.objects.create(
            school=self.school,
            subject=self.mat,
            formula=AcademicRule.Formula.ARITHMETIC,
            passing_grade=Decimal("6.0"),
        )
        self.make_evaluation(self.ana, 4)
        averages = services.subject_averages(self.ana)
        self.assertTrue(averages[0]["below"])

    def test_attendance_stats_percent(self):
        self.make_attendance(self.ana, present=3, absent=1)
        stats = services.attendance_stats(self.ana)
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["percent"], 75.0)

    def test_activity_stats_pending(self):
        Activity.objects.create(
            school=self.school,
            class_group=self.turma,
            subject=self.mat,
            title="Tarefa",
            deadline="2026-12-31",
            created_by=self.prof,
        )
        stats = services.activity_stats(self.ana)
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["delivered"], 0)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["percent"], 0.0)

    def test_activity_stats_delivered(self):
        activity = Activity.objects.create(
            school=self.school,
            class_group=self.turma,
            subject=self.mat,
            title="Tarefa",
            deadline="2026-12-31",
            created_by=self.prof,
        )
        Submission.objects.create(
            school=self.school,
            activity=activity,
            student=self.ana,
            status=Submission.Status.DELIVERED,
        )
        stats = services.activity_stats(self.ana)
        self.assertEqual(stats["delivered"], 1)
        self.assertEqual(stats["percent"], 100.0)

    def test_institutional_indicators(self):
        data = services.institutional_indicators(self.school)
        self.assertEqual(data["students"], 2)
        self.assertEqual(data["class_groups"], 2)


class AccessTests(AnalyticsBase):
    def test_anonymous_redirected(self):
        response = self.client.get(
            reverse("analytics:student_dashboard", args=[self.ana.pk])
        )
        self.assertEqual(response.status_code, 302)

    def test_admin_can_view_student_dashboard(self):
        self.login("adm")
        response = self.client.get(
            reverse("analytics:student_dashboard", args=[self.ana.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ana")

    def test_guardian_sees_own_child_only(self):
        self.login("resp")
        ok = self.client.get(
            reverse("analytics:student_dashboard", args=[self.ana.pk])
        )
        self.assertEqual(ok.status_code, 200)
        denied = self.client.get(
            reverse("analytics:student_dashboard", args=[self.bea.pk])
        )
        self.assertEqual(denied.status_code, 403)

    def test_cross_school_is_denied(self):
        self.login("resp")
        response = self.client.get(
            reverse("analytics:student_dashboard", args=[self.cross.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_professor_only_own_class_dashboard(self):
        self.login("prof")
        ok = self.client.get(
            reverse("analytics:class_dashboard", args=[self.turma.pk])
        )
        self.assertEqual(ok.status_code, 200)
        denied = self.client.get(
            reverse("analytics:class_dashboard", args=[self.turma_b.pk])
        )
        self.assertEqual(denied.status_code, 403)

    def test_institutional_restricted(self):
        self.login("coord")
        self.assertEqual(
            self.client.get(reverse("analytics:institutional_dashboard")).status_code,
            200,
        )
        self.login("prof")
        self.assertEqual(
            self.client.get(reverse("analytics:institutional_dashboard")).status_code,
            403,
        )

    def test_secretaria_panel_restricted(self):
        self.login("sec")
        self.assertEqual(
            self.client.get(reverse("analytics:secretaria_panel")).status_code, 200
        )
        self.login("prof")
        self.assertEqual(
            self.client.get(reverse("analytics:secretaria_panel")).status_code, 403
        )

    def test_observations_hidden_from_admin(self):
        PedagogicalObservation.objects.create(
            school=self.school,
            student=self.ana,
            teacher=self.prof,
            subject=self.mat,
            content="Fracoes",
            dificuldades="Dificuldade com fracoes",
        )
        self.login("coord")
        coord = self.client.get(
            reverse("analytics:student_dashboard", args=[self.ana.pk])
        )
        self.assertContains(coord, "Dificuldade com fracoes")

        self.login("adm")
        admin = self.client.get(
            reverse("analytics:student_dashboard", args=[self.ana.pk])
        )
        self.assertNotContains(admin, "Dificuldade com fracoes")


class ReportTests(AnalyticsBase):
    def test_hub_lists_reports_by_role(self):
        self.login("resp")
        response = self.client.get(reverse("analytics:report_hub"))
        self.assertContains(response, "Boletim individual")
        self.assertNotContains(response, "Relatorio institucional")

    def test_boletim_requires_student(self):
        self.login("coord")
        response = self.client.get(reverse("analytics:report_detail", args=["boletim"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "estudante")

    def test_boletim_runs_for_guardian(self):
        self.make_evaluation(self.ana, 9)
        self.login("resp")
        response = self.client.get(
            reverse("analytics:report_detail", args=["boletim"]),
            {"student": self.ana.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Matematica")

    def test_guardian_cannot_report_other_student(self):
        self.login("resp")
        response = self.client.get(
            reverse("analytics:report_detail", args=["boletim"]),
            {"student": self.bea.pk},
        )
        self.assertEqual(response.status_code, 403)

    def test_csv_has_bom_and_semicolon(self):
        self.make_evaluation(self.ana, 9)
        self.login("resp")
        response = self.client.get(
            reverse("analytics:report_csv", args=["boletim"]),
            {"student": self.ana.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertTrue(response.content.startswith(codecs.BOM_UTF8))
        self.assertIn(b"Disciplina;", response.content)

    def test_cross_school_student_not_found(self):
        self.login("adm")
        response = self.client.get(
            reverse("analytics:report_detail", args=["boletim"]),
            {"student": self.cross.pk},
        )
        self.assertEqual(response.status_code, 404)

    def test_csv_respects_role_scope(self):
        self.login("resp")
        response = self.client.get(
            reverse("analytics:report_csv", args=["institucional"])
        )
        self.assertEqual(response.status_code, 403)

    def test_professor_report_scope(self):
        PedagogicalObservation.objects.create(
            school=self.school,
            student=self.ana,
            teacher=self.prof,
            subject=self.mat,
            content="Algebra",
            dificuldades="Dificuldade em algebra",
        )
        PedagogicalObservation.objects.create(
            school=self.school,
            student=self.bea,
            teacher=self.prof,
            subject=self.mat,
            content="Geometria",
            dificuldades="Dificuldade em geometria",
        )
        self.login("prof")
        response = self.client.get(
            reverse("analytics:report_detail", args=["dificuldades"])
        )
        self.assertContains(response, "algebra")
        self.assertNotContains(response, "geometria")

    def test_print_view_renders(self):
        self.login("coord")
        self.make_evaluation(self.ana, 8)
        response = self.client.get(
            reverse("analytics:report_detail", args=["boletim"]),
            {"student": self.ana.pk, "print": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no-print")
        self.assertContains(response, "Boletim")


class ChartTests(TestCase):
    def test_line_chart_empty(self):
        self.assertIn(b"chart-empty", charts.line_chart([]).encode())

    def test_bar_chart_escapes_labels(self):
        svg = charts.bar_chart([{"label": "<b>x</b>", "value": 3}])
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", svg)
        self.assertNotIn("<b>x</b>", svg)

    def test_gauge_marks_danger(self):
        html = charts.gauge(70, limit=25)
        self.assertIn("danger", html)
