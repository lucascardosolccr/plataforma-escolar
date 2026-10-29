from django.urls import reverse

from apps.academics.models import ClassGroup, SchoolYear
from apps.registry.models import Enrollment, GuardianLink, Student

from .test_registry import RegistryBase


class GuardianLinkRemediationTests(RegistryBase):
    def test_duplicate_guardian_link_is_rejected(self):
        self.client.login(username="sec", password="senha-forte-1")
        data = {
            "guardian": self.resp.pk,
            "student": self.student_a.pk,
            "relation": "pai",
        }
        self.client.post(reverse("link_create"), data)
        resp = self.client.post(reverse("link_create"), data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            GuardianLink.objects.filter(
                guardian=self.resp, student=self.student_a
            ).count(),
            1,
        )

    def test_rejection_records_validation_time(self):
        link = GuardianLink.objects.create(
            school=self.school,
            guardian=self.resp,
            student=self.student_a,
            status="pendente",
            requested_by=self.resp,
        )
        self.client.login(username="sec", password="senha-forte-1")
        self.client.post(
            reverse("link_reject", args=[link.pk]),
            {"reason": "Documento ilegível"},
        )
        link.refresh_from_db()
        self.assertEqual(link.status, "rejeitado")
        self.assertIsNotNone(link.validated_at)

    def test_guardian_detail_hides_other_guardians(self):
        GuardianLink.objects.create(
            school=self.school,
            guardian=self.resp,
            student=self.student_a,
            status="aprovado",
        )
        GuardianLink.objects.create(
            school=self.school,
            guardian=self.resp_2,
            student=self.student_a,
            status="aprovado",
        )
        self.client.login(username="resp", password="senha-forte-1")
        resp = self.client.get(
            reverse("student_detail", args=[self.student_a.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "resp2")


class EnrollmentRemediationTests(RegistryBase):
    def setUp(self):
        super().setUp()
        self.year = SchoolYear.objects.create(school=self.school, name="2026")
        self.turma = ClassGroup.objects.create(
            school=self.school,
            school_year=self.year,
            name="1 Ano A",
        )
        self.enrollment = Enrollment.objects.create(
            school=self.school,
            student=self.student_a,
            class_group=self.turma,
            school_year=self.year,
            status="ativo",
        )
        self.other_student = Student.objects.create(
            school=self.school,
            first_name="Outra",
        )

    def test_editing_enrollment_cannot_replace_student(self):
        self.client.login(username="sec", password="senha-forte-1")
        self.client.post(
            reverse("enrollment_edit", args=[self.enrollment.pk]),
            {
                "student": self.other_student.pk,
                "class_group": self.turma.pk,
                "school_year": self.year.pk,
                "enrollment_number": "",
                "status": "ativo",
                "started_on": "",
                "ended_on": "",
            },
        )
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.student_id, self.student_a.pk)
