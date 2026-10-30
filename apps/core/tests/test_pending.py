"""Central de pendências por perfil (Prompt 14, rodada 10)."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.core.models import Role, School, User
from apps.core.pending import for_user
from apps.pedagogy.models import AbsenceJustification, Activity, AttendanceRecord, Submission
from apps.registry.models import Enrollment, GuardianLink, Student, StudentApplication

PW = "Senha-forte-123"


class PendingTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        year = SchoolYear.objects.create(school=self.school, name="2026", is_current=True)
        self.cg = ClassGroup.objects.create(school=self.school, school_year=year, name="2º A")
        self.other = ClassGroup.objects.create(school=self.school, school_year=year, name="2º B")
        mat = Subject.objects.create(school=self.school, name="Matemática")
        mk = lambda u, r: User.objects.create_user(u, password=PW, role=r, school=self.school)
        self.prof, self.sec, self.fam = mk("prof", Role.PROFESSOR), mk("sec", Role.SECRETARIA), mk("fam", Role.RESPONSAVEL)
        TeacherAssignment.objects.create(school=self.school, school_year=year, teacher=self.prof,
                                         class_group=self.cg, subject=mat)
        self.ana = Student.objects.create(school=self.school, first_name="Ana")
        Enrollment.objects.create(school=self.school, student=self.ana, class_group=self.cg, school_year=year)
        GuardianLink.objects.create(school=self.school, guardian=self.fam, student=self.ana, status="aprovado")
        act = Activity.objects.create(school=self.school, class_group=self.cg, subject=mat, title="Lista",
                                      created_by=self.prof, status="publicada",
                                      published_date=timezone.localdate() - timedelta(days=10),
                                      deadline=timezone.localdate() - timedelta(days=2))
        Submission.objects.create(school=self.school, activity=act, student=self.ana, status="entregue")

    def counts(self, user):
        return {i["label"]: i["count"] for i in for_user(User.objects.get(pk=user.pk))}

    def test_teacher_sees_missing_attendance_and_grading(self):
        c = self.counts(self.prof)
        self.assertEqual(c["Entregas recebidas aguardando correção"], 1)
        self.assertGreaterEqual(c["Chamadas sem registro nos últimos dias letivos"], 1)
        # Só a turma dele: a 2º B não entra na conta.
        self.assertLessEqual(c["Chamadas sem registro nos últimos dias letivos"], 5)

    def test_family_unjustified_absences_and_justification_covers(self):
        d = timezone.localdate() - timedelta(days=3)
        AttendanceRecord.objects.create(school=self.school, class_group=self.cg, student=self.ana, date=d,
                                        status="falta", recorded_by=self.prof)
        self.assertEqual(self.counts(self.fam)["Faltas dos últimos 30 dias sem justificativa enviada"], 1)
        AbsenceJustification.objects.create(school=self.school, student=self.ana, start_date=d, end_date=d,
                                            reason="Consulta", submitted_by=self.fam)
        self.assertNotIn("Faltas dos últimos 30 dias sem justificativa enviada", self.counts(self.fam))

    def test_secretaria_sees_applications_and_page_opens_for_all(self):
        StudentApplication.objects.create(school=self.school, guardian=self.fam, status="enviado",
                                          first_name="Novo")
        self.assertEqual(self.counts(self.sec)["Pré-cadastros enviados pelas famílias"], 1)
        for u in (self.prof, self.sec, self.fam):
            self.client.logout()
            self.client.login(username=u.username, password=PW)
            self.assertEqual(self.client.get(reverse("pending_center")).status_code, 200)
        self.assertContains(self.client.get(reverse("home")), "pendência")
