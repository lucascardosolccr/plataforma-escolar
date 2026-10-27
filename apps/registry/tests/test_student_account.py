"""Conta de acesso do próprio estudante.

O foco destes testes é o que o estudante NÃO pode ver: ocorrências,
observações pedagógicas, anotações da secretaria e dados dos colegas. O
Prompt 3 §7.5 é explícito nisso, e são dados de menor.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.core.models import AuditLog, Role, School
from apps.pedagogy.models import (
    Activity,
    AttendanceRecord,
    Evaluation,
    Grade,
    InterventionPlan,
    Occurrence,
    PedagogicalObservation,
)
from apps.registry.access import can_create_student_account, is_own_record, student_of
from apps.registry.models import Enrollment, GuardianLink, Student

User = get_user_model()
PW = "senha-forte-1"


class StudentAccountBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola A", code="a")

        def mk(username, role):
            return User.objects.create_user(
                username=username, password=PW, role=role, school=self.school
            )

        self.admin = mk("adm", Role.ADMIN)
        self.sec = mk("sec", Role.SECRETARIA)
        self.coord = mk("coord", Role.COORDENACAO)
        self.prof = mk("prof", Role.PROFESSOR)
        self.resp = mk("resp", Role.RESPONSAVEL)

        self.year = SchoolYear.objects.create(school=self.school, name="2026")
        self.turma = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="1º Ano A"
        )
        self.mat = Subject.objects.create(school=self.school, name="Matemática")
        TeacherAssignment.objects.create(
            school=self.school, school_year=self.year, teacher=self.prof,
            class_group=self.turma, subject=self.mat,
        )
        self.ana = Student.objects.create(school=self.school, first_name="Ana")
        self.bia = Student.objects.create(school=self.school, first_name="Bia")
        for s in (self.ana, self.bia):
            Enrollment.objects.create(
                school=self.school, student=s, class_group=self.turma,
                school_year=self.year,
            )
        GuardianLink.objects.create(
            school=self.school, guardian=self.resp, student=self.ana, status="aprovado"
        )

    def login(self, username, password=PW):
        self.assertTrue(self.client.login(username=username, password=password))

    def create_account_via_view(self, student):
        """Cria a conta pela via oficial; devolve (conta, senha temporária)."""
        self.login("sec")
        resp = self.client.post(
            reverse("student_account_create", args=[student.pk])
        )
        self.assertEqual(resp.status_code, 200)
        student.refresh_from_db()
        self.client.logout()
        return student.user, resp.context["temp_password"]

    def give_account(self, student):
        """Como acima, mas com senha conhecida e sem troca obrigatória.

        A senha temporária e a troca obrigatória têm cobertura própria
        (AccountCreationTests e core/tests/test_password_reset.py); aqui o que
        interessa é navegar como o estudante.
        """
        conta, _ = self.create_account_via_view(student)
        conta.set_password(PW)
        conta.must_change_password = False
        conta.save(update_fields=["password", "must_change_password"])
        return conta, PW


class AccountCreationTests(StudentAccountBase):
    def test_secretaria_creates_account_linked_to_the_student(self):
        self.login("sec")
        resp = self.client.post(reverse("student_account_create", args=[self.ana.pk]))
        self.ana.refresh_from_db()
        self.assertIsNotNone(self.ana.user)
        self.assertEqual(self.ana.user.role, Role.ESTUDANTE.value)
        self.assertEqual(self.ana.user.school, self.school)
        self.assertTrue(self.ana.user.must_change_password)
        self.assertContains(resp, resp.context["temp_password"])

    def test_created_account_can_actually_log_in(self):
        conta, senha = self.create_account_via_view(self.ana)
        self.assertTrue(self.client.login(username=conta.username, password=senha))

    def test_requires_post(self):
        self.login("sec")
        self.assertEqual(
            self.client.get(
                reverse("student_account_create", args=[self.ana.pk])
            ).status_code,
            405,
        )

    def test_teacher_and_guardian_cannot_create_account(self):
        for who in ("prof", "resp", "coord"):
            self.login(who)
            self.assertEqual(
                self.client.post(
                    reverse("student_account_create", args=[self.ana.pk])
                ).status_code,
                403,
                f"{who} não deveria criar acesso de estudante",
            )
            self.client.logout()

    def test_creation_is_audited(self):
        self.login("sec")
        self.client.post(reverse("student_account_create", args=[self.ana.pk]))
        self.assertTrue(
            AuditLog.objects.filter(
                user=self.sec, detail__contains="Criou o acesso do estudante Ana"
            ).exists()
        )

    def test_second_call_resets_password_without_duplicating_account(self):
        conta, senha = self.create_account_via_view(self.ana)
        self.login("sec")
        resp = self.client.post(reverse("student_account_create", args=[self.ana.pk]))
        nova = resp.context["temp_password"]
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.user_id, conta.pk)
        self.assertNotEqual(nova, senha)
        conta.refresh_from_db()
        self.assertTrue(conta.check_password(nova))
        self.assertFalse(conta.check_password(senha))

    def test_usernames_do_not_collide(self):
        outra = Student.objects.create(school=self.school, first_name="Ana")
        c1, _ = self.give_account(self.ana)
        c2, _ = self.give_account(outra)
        self.assertNotEqual(c1.username, c2.username)

    def test_student_role_is_not_offered_in_professional_account_form(self):
        """A conta de estudante só nasce a partir da ficha, com matrícula."""
        self.login("adm")
        corpo = self.client.get(reverse("user_create")).content.decode()
        self.assertNotIn('value="estudante"', corpo)

    def test_public_signup_cannot_create_a_student(self):
        self.client.logout()
        self.client.post(
            reverse("signup"),
            {
                "school_code": "a",
                "username": "tentativa",
                "first_name": "T",
                "last_name": "T",
                "email": "t@t.test",
                "password1": "uma-senha-forte-3",
                "password2": "uma-senha-forte-3",
            },
        )
        criado = User.objects.filter(username="tentativa").first()
        if criado:
            self.assertEqual(criado.role, Role.RESPONSAVEL.value)


class StudentSeesOwnDataTests(StudentAccountBase):
    def setUp(self):
        super().setUp()
        self.conta, _ = self.give_account(self.ana)
        self.act = Activity.objects.create(
            school=self.school, class_group=self.turma, subject=self.mat,
            title="Dever da turma", description="Exercícios.", created_by=self.prof,
            status=Activity.Status.PUBLISHED, published_date=date(2026, 3, 1),
        )
        self.login(self.conta.username)

    def test_helpers_resolve_the_student(self):
        self.assertEqual(student_of(self.conta), self.ana)
        self.assertTrue(is_own_record(self.conta, self.ana))
        self.assertFalse(is_own_record(self.conta, self.bia))

    def test_sees_own_class_activities(self):
        resp = self.client.get(reverse("pedagogy:activity_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Dever da turma")
        self.assertContains(resp, "Minhas atividades")

    def test_does_not_see_draft(self):
        Activity.objects.create(
            school=self.school, class_group=self.turma, subject=self.mat,
            title="Rascunho oculto", description="x", created_by=self.prof,
            status=Activity.Status.DRAFT, published_date=date(2026, 3, 1),
        )
        resp = self.client.get(reverse("pedagogy:activity_list"))
        self.assertNotContains(resp, "Rascunho oculto")

    def test_sees_published_evaluations_only(self):
        Evaluation.objects.create(
            school=self.school, subject=self.mat, class_group=self.turma,
            title="Prova publicada", status=Evaluation.Status.PUBLISHED,
            created_by=self.prof,
        )
        Evaluation.objects.create(
            school=self.school, subject=self.mat, class_group=self.turma,
            title="Prova em rascunho", status=Evaluation.Status.DRAFT,
            created_by=self.prof,
        )
        resp = self.client.get(reverse("pedagogy:evaluation_list"))
        self.assertContains(resp, "Prova publicada")
        self.assertNotContains(resp, "Prova em rascunho")

    def test_sees_only_own_attendance_row(self):
        for s in (self.ana, self.bia):
            AttendanceRecord.objects.create(
                school=self.school, class_group=self.turma, student=s,
                date="2026-03-10", status="falta", recorded_by=self.prof,
            )
        resp = self.client.get(
            reverse("pedagogy:attendance_class", args=[self.turma.pk])
        )
        self.assertContains(resp, "Ana")
        self.assertNotContains(resp, "Bia")

    def test_sees_own_record_and_dashboard(self):
        self.assertEqual(
            self.client.get(reverse("student_detail", args=[self.ana.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse("analytics:student_dashboard", args=[self.ana.pk])
            ).status_code,
            200,
        )


class StudentCannotSeeTests(StudentAccountBase):
    def setUp(self):
        super().setUp()
        self.conta, _ = self.give_account(self.ana)
        self.login(self.conta.username)

    def test_cannot_open_another_students_record(self):
        self.assertEqual(
            self.client.get(reverse("student_detail", args=[self.bia.pk])).status_code,
            403,
        )

    def test_cannot_open_another_students_dashboard(self):
        self.assertEqual(
            self.client.get(
                reverse("analytics:student_dashboard", args=[self.bia.pk])
            ).status_code,
            403,
        )

    def test_cannot_list_occurrences(self):
        self.assertEqual(
            self.client.get(reverse("pedagogy:occurrence_list")).status_code, 403
        )

    def test_cannot_list_observations(self):
        self.assertEqual(
            self.client.get(reverse("pedagogy:observation_list")).status_code, 403
        )

    def test_cannot_list_plans(self):
        self.assertEqual(
            self.client.get(reverse("pedagogy:plan_list")).status_code, 403
        )

    def test_own_dashboard_hides_discipline_and_pedagogical_notes(self):
        """O painel próprio não mostra o registro disciplinar nem anotações."""
        Occurrence.objects.create(
            school=self.school, student=self.ana, recorded_by=self.coord,
            date=date(2026, 3, 5), description="Conversa em sala",
        )
        PedagogicalObservation.objects.create(
            school=self.school, student=self.ana, teacher=self.prof,
            content="Leitura", dificuldades="Troca letras",
        )
        InterventionPlan.objects.create(
            school=self.school, student=self.ana, title="Plano de reforço",
            description="Objetivos", created_by=self.coord,
        )
        resp = self.client.get(
            reverse("analytics:student_dashboard", args=[self.ana.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["can_view_occ"])
        self.assertFalse(resp.context["can_view_plan"])
        self.assertFalse(resp.context["can_view_obs"])
        self.assertNotContains(resp, "Conversa em sala")
        self.assertNotContains(resp, "Troca letras")
        self.assertNotContains(resp, "Plano de reforço")
        self.assertNotContains(resp, "Ocorrências abertas")

    def test_own_record_hides_secretary_notes(self):
        self.ana.notes = "Anotação interna da secretaria"
        self.ana.save(update_fields=["notes"])
        resp = self.client.get(reverse("student_detail", args=[self.ana.pk]))
        self.assertNotContains(resp, "Anotação interna da secretaria")

    def test_cannot_reach_reports_or_panels(self):
        for nome in (
            "analytics:report_hub",
            "analytics:institutional_dashboard",
            "analytics:secretaria_panel",
        ):
            self.assertEqual(
                self.client.get(reverse(nome)).status_code, 403, nome
            )

    def test_cannot_create_or_manage_activities(self):
        self.assertEqual(
            self.client.get(reverse("pedagogy:activity_create")).status_code, 403
        )

    def test_cannot_manage_registry(self):
        for nome in ("student_list", "guardian_list", "enrollment_list", "user_list"):
            self.assertEqual(self.client.get(reverse(nome)).status_code, 403, nome)

    def test_cannot_create_another_student_account(self):
        self.assertFalse(can_create_student_account(self.conta, self.bia))
        self.assertEqual(
            self.client.post(
                reverse("student_account_create", args=[self.bia.pk])
            ).status_code,
            403,
        )


class GradeVisibilityTests(StudentAccountBase):
    def test_student_sees_own_published_grade_in_dashboard(self):
        conta, _ = self.give_account(self.ana)
        ev = Evaluation.objects.create(
            school=self.school, subject=self.mat, class_group=self.turma,
            title="Prova", status=Evaluation.Status.PUBLISHED, created_by=self.prof,
        )
        Grade.objects.create(
            school=self.school, evaluation=ev, student=self.ana,
            value="9.00", updated_by=self.prof,
        )
        Grade.objects.create(
            school=self.school, evaluation=ev, student=self.bia,
            value="4.00", updated_by=self.prof,
        )
        self.login(conta.username)
        resp = self.client.get(
            reverse("analytics:student_dashboard", args=[self.ana.pk])
        )
        medias = resp.context["subject_averages"]
        valores = [m["average"] for m in medias if m.get("average") is not None]
        # Só a própria nota entra: a média da Bia não contamina.
        self.assertEqual([float(v) for v in valores], [9.0])
