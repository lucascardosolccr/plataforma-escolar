from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from PIL import Image

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.core.models import AuditLog, Role, School
from apps.registry.models import Enrollment, GuardianLink, Student

User = get_user_model()


def png_bytes():
    buf = BytesIO()
    Image.new("RGB", (4, 4), (0, 120, 200)).save(buf, format="PNG")
    buf.seek(0)
    return buf


class RegistryBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola A", code="a")
        self.school_b = School.objects.create(name="Escola B", code="b")
        self.secretaria = User.objects.create_user(
            username="sec", password="senha-forte-1", role=Role.SECRETARIA, school=self.school
        )
        self.coord = User.objects.create_user(
            username="coord", password="senha-forte-1", role=Role.COORDENACAO, school=self.school
        )
        self.prof = User.objects.create_user(
            username="prof", password="senha-forte-1", role=Role.PROFESSOR, school=self.school
        )
        self.prof_other = User.objects.create_user(
            username="prof2", password="senha-forte-1", role=Role.PROFESSOR, school=self.school
        )
        self.resp = User.objects.create_user(
            username="resp", password="senha-forte-1", role=Role.RESPONSAVEL, school=self.school
        )
        self.resp_2 = User.objects.create_user(
            username="resp2", password="senha-forte-1", role=Role.RESPONSAVEL, school=self.school
        )
        self.sec_b = User.objects.create_user(
            username="secb", password="senha-forte-1", role=Role.SECRETARIA, school=self.school_b
        )
        self.student_a = Student.objects.create(
            school=self.school, first_name="Ana", last_name="Silva"
        )
        self.student_b = Student.objects.create(
            school=self.school_b, first_name="Bia", last_name="Lima"
        )
        self.client.defaults = {"HTTP_X_FORWARDED_FOR": "1.2.3.4"}


class StudentCrudTests(RegistryBase):
    def test_create_student_updates_lists(self):
        self.client.login(username="sec", password="senha-forte-1")
        resp = self.client.post(
            "/estudantes/novo/",
            {"first_name": "Carla", "last_name": "Pereira", "status": "ativo"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Student.objects.filter(first_name="Carla").exists())
        self.assertTrue(
            AuditLog.objects.filter(
                action="create", target_type="Student", user=self.secretaria
            ).exists()
        )

    def test_professor_cannot_create_student(self):
        self.client.login(username="prof", password="senha-forte-1")
        self.assertEqual(self.client.get("/estudantes/novo/").status_code, 403)

    def test_responsavel_cannot_create_student(self):
        self.client.login(username="resp", password="senha-forte-1")
        self.assertEqual(self.client.get("/estudantes/novo/").status_code, 403)

    def test_anonymous_redirected(self):
        resp = self.client.get("/estudantes/novo/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp.url)

    def test_edit_student_is_isolated(self):
        self.client.login(username="secb", password="senha-forte-1")
        resp = self.client.get(f"/estudantes/{self.student_a.pk}/editar/")
        self.assertEqual(resp.status_code, 404)

    def test_list_isolated_between_schools(self):
        self.client.login(username="secb", password="senha-forte-1")
        resp = self.client.get("/estudantes/")
        self.assertContains(resp, "Bia")
        self.assertNotContains(resp, "Ana")


class GuardianLinkFlowTests(RegistryBase):
    def test_responsavel_cannot_view_student_before_approval(self):
        self.client.login(username="resp", password="senha-forte-1")
        self.assertEqual(
            self.client.get(f"/estudantes/{self.student_a.pk}/").status_code, 403
        )

    def test_responsavel_requests_link_by_name(self):
        self.client.login(username="resp", password="senha-forte-1")
        resp = self.client.post(
            "/vinculos/solicitar/",
            {"student_name": "Ana Silva", "relation": "mae"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        link = GuardianLink.objects.get(guardian=self.resp, student=self.student_a)
        self.assertEqual(link.status, "pendente")
        self.assertTrue(
            AuditLog.objects.filter(action="create", target_type="GuardianLink").exists()
        )

    def test_responsavel_request_wrong_name_rejected(self):
        self.client.login(username="resp", password="senha-forte-1")
        resp = self.client.post(
            "/vinculos/solicitar/",
            {"student_name": "Nome Que Nao Existe", "relation": "mae"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Nenhum estudante ativo")
        self.assertFalse(GuardianLink.objects.exists())

    def test_duplicate_link_request_blocked(self):
        self.client.login(username="resp", password="senha-forte-1")
        self.client.post(
            "/vinculos/solicitar/", {"student_name": "Ana Silva", "relation": "mae"}
        )
        resp = self.client.post(
            "/vinculos/solicitar/", {"student_name": "Ana Silva", "relation": "mae"}
        )
        self.assertContains(resp, "Já existe um vínculo")

    def test_secretaria_approve_grants_access(self):
        self.client.login(username="resp", password="senha-forte-1")
        self.client.post(
            "/vinculos/solicitar/", {"student_name": "Ana Silva", "relation": "mae"}
        )
        link = GuardianLink.objects.get(guardian=self.resp, student=self.student_a)

        self.client.login(username="sec", password="senha-forte-1")
        resp = self.client.post(f"/vinculos/{link.pk}/aprovar/", follow=True)
        self.assertEqual(resp.status_code, 200)
        link.refresh_from_db()
        self.assertEqual(link.status, "aprovado")
        self.assertEqual(link.validated_by, self.secretaria)
        self.assertTrue(AuditLog.objects.filter(action="approve").exists())

        self.client.login(username="resp", password="senha-forte-1")
        resp = self.client.get(f"/estudantes/{self.student_a.pk}/")
        self.assertEqual(resp.status_code, 200)

    def test_secretaria_reject_denies_access(self):
        link = GuardianLink.objects.create(
            school=self.school,
            guardian=self.resp,
            student=self.student_a,
            status="pendente",
            requested_by=self.resp,
        )
        self.client.login(username="sec", password="senha-forte-1")
        self.client.post(f"/vinculos/{link.pk}/rejeitar/", {"reason": "sem documento"}, follow=True)
        link.refresh_from_db()
        self.assertEqual(link.status, "rejeitado")
        self.assertEqual(link.rejection_reason, "sem documento")

        self.client.login(username="resp", password="senha-forte-1")
        self.assertEqual(
            self.client.get(f"/estudantes/{self.student_a.pk}/").status_code, 403
        )

    def test_other_family_cannot_view_student(self):
        GuardianLink.objects.create(
            school=self.school,
            guardian=self.resp,
            student=self.student_a,
            status="aprovado",
            validated_by=self.secretaria,
        )
        self.client.login(username="resp2", password="senha-forte-1")
        self.assertEqual(
            self.client.get(f"/estudantes/{self.student_a.pk}/").status_code, 403
        )

    def test_link_create_by_secretaria_is_validated(self):
        self.client.login(username="sec", password="senha-forte-1")
        self.client.post(
            "/vinculos/novo/",
            {"guardian": self.resp.pk, "student": self.student_a.pk, "relation": "pai"},
        )
        link = GuardianLink.objects.get(guardian=self.resp, student=self.student_a)
        self.assertEqual(link.status, "aprovado")

    def test_only_secretaria_and_admin_validate(self):
        self.client.login(username="coord", password="senha-forte-1")
        link = GuardianLink.objects.create(
            school=self.school,
            guardian=self.resp,
            student=self.student_a,
            status="pendente",
            requested_by=self.resp,
        )
        self.assertEqual(self.client.post(f"/vinculos/{link.pk}/aprovar/").status_code, 403)

    def test_link_approve_and_reject_require_post(self):
        self.client.login(username="sec", password="senha-forte-1")
        link = GuardianLink.objects.create(
            school=self.school,
            guardian=self.resp,
            student=self.student_a,
            status="pendente",
            requested_by=self.resp,
        )
        self.assertEqual(self.client.get(f"/vinculos/{link.pk}/aprovar/").status_code, 405)
        self.assertEqual(self.client.get(f"/vinculos/{link.pk}/rejeitar/").status_code, 405)
        link.refresh_from_db()
        self.assertEqual(link.status, "pendente")


class EnrollmentTests(RegistryBase):
    def setUp(self):
        super().setUp()
        self.year = SchoolYear.objects.create(school=self.school, name="2026")
        self.turma = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="1º Ano A", grade="1º ano"
        )
        self.subj = Subject.objects.create(school=self.school, name="Matemática")

    def test_enrollment_and_professor_visibility(self):
        TeacherAssignment.objects.create(
            school=self.school,
            school_year=self.year,
            teacher=self.prof,
            class_group=self.turma,
            subject=self.subj,
        )
        self.client.login(username="sec", password="senha-forte-1")
        self.client.post(
            "/matriculas/nova/",
            {
                "student": self.student_a.pk,
                "class_group": self.turma.pk,
                "school_year": self.year.pk,
                "status": "ativo",
            },
            follow=True,
        )
        self.assertTrue(
            Enrollment.objects.filter(student=self.student_a, school_year=self.year).exists()
        )

        self.client.login(username="prof", password="senha-forte-1")
        resp = self.client.get("/minhas-turmas/")
        self.assertContains(resp, "Ana")
        self.assertEqual(
            self.client.get(f"/estudantes/{self.student_a.pk}/").status_code, 200
        )

    def test_professor_without_assignment_blocked(self):
        self.client.login(username="prof2", password="senha-forte-1")
        self.assertEqual(
            self.client.get(f"/estudantes/{self.student_a.pk}/").status_code, 403
        )
        self.assertEqual(self.client.get("/minhas-turmas/").status_code, 200)

    def test_duplicate_active_enrollment_blocked(self):
        self.client.login(username="sec", password="senha-forte-1")
        data = {
            "student": self.student_a.pk,
            "class_group": self.turma.pk,
            "school_year": self.year.pk,
            "status": "ativo",
        }
        self.client.post("/matriculas/nova/", data, follow=True)
        resp = self.client.post("/matriculas/nova/", data)
        self.assertContains(resp, "já possui matrícula")

    def test_enrollment_form_rejects_other_school(self):
        year_b = SchoolYear.objects.create(school=self.school_b, name="2026")
        self.client.login(username="sec", password="senha-forte-1")
        resp = self.client.post(
            "/matriculas/nova/",
            {
                "student": self.student_a.pk,
                "class_group": self.turma.pk,
                "school_year": year_b.pk,
                "status": "ativo",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            Enrollment.objects.filter(
                student=self.student_a, school_year=year_b
            ).exists()
        )


class PhotoProtectionTests(RegistryBase):
    def test_student_photo_publicly_inaccessible(self):
        student = Student.objects.create(
            school=self.school,
            first_name="Fotogenica",
            photo="photos/not-real-placeholder.jpg",
        )
        resp = self.client.get(f"/estudantes/{student.pk}/foto/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp.url)

    def test_photo_upload_and_authorized_access(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.login(username="sec", password="senha-forte-1")
        resp = self.client.post(
            "/estudantes/novo/",
            {
                "first_name": "Foto",
                "last_name": "Teste",
                "status": "ativo",
                "photo": SimpleUploadedFile(
                    "foto.png", png_bytes().getvalue(), content_type="image/png"
                ),
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        student = Student.objects.get(first_name="Foto")
        self.assertTrue(student.photo.name.startswith("photos/"))

        GuardianLink.objects.create(
            school=self.school, guardian=self.resp, student=student, status="aprovado"
        )
        self.client.login(username="resp", password="senha-forte-1")
        resp = self.client.get(f"/estudantes/{student.pk}/foto/")
        self.assertEqual(resp.status_code, 200)

    def test_guardian_photo_isolated_between_schools(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.registry.models import GuardianProfile

        GuardianProfile.objects.create(
            user=self.resp,
            photo=SimpleUploadedFile(
                "g.png", png_bytes().getvalue(), content_type="image/png"
            ),
        )
        self.client.login(username="sec", password="senha-forte-1")
        self.assertEqual(
            self.client.get(f"/responsaveis/{self.resp.pk}/foto/").status_code, 200
        )

        resp_b = User.objects.create_user(
            username="respb", password="senha-forte-1", role=Role.RESPONSAVEL, school=self.school_b
        )
        GuardianProfile.objects.create(user=resp_b, photo="photos/placeholder.jpg")
        self.client.login(username="sec", password="senha-forte-1")
        self.assertEqual(
            self.client.get(f"/responsaveis/{resp_b.pk}/foto/").status_code, 403
        )

    def test_invalid_photo_type_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.login(username="sec", password="senha-forte-1")
        self.client.post(
            "/estudantes/novo/",
            {
                "first_name": "Mau",
                "last_name": "Arquivo",
                "status": "ativo",
                "photo": SimpleUploadedFile("evil.exe", b"MZ\x90\x00", content_type="application/x-msdownload"),
            },
        )
        self.assertFalse(Student.objects.filter(first_name="Mau").exists())

    def test_invalid_image_content_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.login(username="sec", password="senha-forte-1")
        self.client.post(
            "/estudantes/novo/",
            {
                "first_name": "Mau2",
                "last_name": "Arquivo",
                "status": "ativo",
                "photo": SimpleUploadedFile("fake.png", b"not a real image", content_type="image/png"),
            },
        )
        self.assertFalse(Student.objects.filter(first_name="Mau2").exists())