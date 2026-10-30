"""Fotografia de todos os perfis, pendências, cobrança e dispensas (Prompt 14, rodada 3)."""

import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.communication.models import Notification
from apps.core.models import AuditLog, Role, School, User
from apps.registry.models import GuardianLink, GuardianProfile, PhotoException, Student
from apps.registry.tests.test_import import png_bytes

PW = "Senha-forte-123"


class PhotoBase(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        ctx = override_settings(MEDIA_ROOT=self.media)
        ctx.enable()
        self.addCleanup(ctx.disable)
        self.school = School.objects.create(name="Escola", code="e")
        self.users = {r: User.objects.create_user(r, password=PW, role=r, school=self.school, first_name=r.title())
                      for r in Role.values}
        self.ana = Student.objects.create(school=self.school, first_name="Ana", status="ativo")
        self.bia = Student.objects.create(school=self.school, first_name="Bia", status="ativo")
        GuardianLink.objects.create(school=self.school, guardian=self.users[Role.RESPONSAVEL], student=self.ana,
                                    status="aprovado")

    def login(self, role):
        self.client.logout()
        self.client.login(username=role, password=PW)

    def upload(self, **kw):
        return SimpleUploadedFile("f.jpg", png_bytes(**kw))


class OwnPhotoTests(PhotoBase):
    def test_staff_and_family_save_their_own_photo(self):
        from PIL import Image

        self.login(Role.PROFESSOR)
        self.client.post(reverse("my_photo"), {"photo": self.upload(exif_gps=True)})
        prof = User.objects.get(username=Role.PROFESSOR)
        with Image.open(prof.photo.path) as img:
            self.assertEqual(img.size, (512, 512))
            self.assertNotIn(0x8825, img.getexif())
        self.login(Role.RESPONSAVEL)
        self.client.post(reverse("my_photo"), {"photo": self.upload()})
        self.assertTrue(GuardianProfile.objects.get(user__username=Role.RESPONSAVEL).photo)

    def test_student_account_cannot_change_photo_here(self):
        self.login(Role.ESTUDANTE)
        page = self.client.get(reverse("my_photo"))
        self.assertContains(page, "cuidada pela secretaria")
        self.assertNotContains(page, 'name="photo"')

    def test_home_reminds_until_photo_exists(self):
        self.login(Role.PROFESSOR)
        self.assertContains(self.client.get(reverse("home")), "ainda não tem foto")
        self.client.post(reverse("my_photo"), {"photo": self.upload()})
        self.assertNotContains(self.client.get(reverse("home")), "ainda não tem foto")

    def test_staff_photo_visibility(self):
        prof = self.users[Role.PROFESSOR]
        self.login(Role.PROFESSOR)
        self.client.post(reverse("my_photo"), {"photo": self.upload()})
        self.login(Role.RESPONSAVEL)  # família da escola reconhece a professora
        self.assertEqual(self.client.get(reverse("user_photo", args=[prof.pk])).status_code, 200)
        other = School.objects.create(name="Outra", code="o")
        User.objects.create_user("fora", password=PW, role=Role.DIRECAO, school=other)
        self.client.logout()
        self.client.login(username="fora", password=PW)
        self.assertEqual(self.client.get(reverse("user_photo", args=[prof.pk])).status_code, 404)
        # Foto de família nunca sai por esta rota.
        fam = self.users[Role.RESPONSAVEL]
        self.login(Role.PROFESSOR)
        self.assertEqual(self.client.get(reverse("user_photo", args=[fam.pk])).status_code, 404)

    def test_admin_uploads_staff_photo(self):
        self.login(Role.ADMIN)
        prof = self.users[Role.PROFESSOR]
        self.client.post(reverse("staff_photo_upload", args=[prof.pk]), {"photo": self.upload()})
        prof.refresh_from_db()
        self.assertTrue(prof.photo)
        self.login(Role.SECRETARIA)
        resp = self.client.post(reverse("staff_photo_upload", args=[prof.pk]), {"photo": self.upload()})
        self.assertEqual(resp.status_code, 403)

    def test_student_form_photo_is_processed(self):
        from PIL import Image

        self.login(Role.SECRETARIA)
        self.client.post(reverse("student_edit", args=[self.ana.pk]), {
            "first_name": "Ana", "status": "ativo", "photo": SimpleUploadedFile("a.png", png_bytes(size=(900, 700)))})
        self.ana.refresh_from_db()
        with Image.open(self.ana.photo.path) as img:
            self.assertEqual((img.format, img.size), ("JPEG", (512, 512)))


class PendingTests(PhotoBase):
    def test_pending_list_roles_and_exception(self):
        for role, code in ((Role.SECRETARIA, 200), (Role.DIRECAO, 200), (Role.ADMIN, 200),
                           (Role.PROFESSOR, 403), (Role.RESPONSAVEL, 403), (Role.COORDENACAO, 403)):
            self.login(role)
            self.assertEqual(self.client.get(reverse("photo_pending")).status_code, code, role)
        self.login(Role.SECRETARIA)
        page = self.client.get(reverse("photo_pending"))
        self.assertContains(page, "Ana")
        self.assertContains(page, "Bia")
        # Secretaria não dispensa; administração dispensa com justificativa.
        resp = self.client.post(reverse("photo_exception_create"), {"kind": "estudante", "id": self.bia.pk, "reason": "x"})
        self.assertEqual(resp.status_code, 403)
        self.login(Role.DIRECAO)
        self.client.post(reverse("photo_exception_create"), {"kind": "estudante", "id": self.bia.pk,
                                                             "reason": "Decisão judicial"})
        self.assertTrue(PhotoException.objects.filter(student=self.bia).exists())
        self.assertTrue(AuditLog.objects.filter(detail__contains="Dispensou a fotografia de Bia").exists())
        page = self.client.get(reverse("photo_pending"))
        self.assertEqual([s.first_name for s in page.context["rows"]], ["Ana"])

    def test_remind_notifies_linked_family_once_a_day(self):
        self.login(Role.SECRETARIA)
        self.client.post(reverse("photo_remind"), {"aba": "estudantes", "ids": [self.ana.pk, self.bia.pk]})
        self.client.post(reverse("photo_remind"), {"aba": "estudantes", "ids": [self.ana.pk]})
        avisos = Notification.objects.filter(kind="foto")
        self.assertEqual(avisos.count(), 1)  # Bia não tem família; Ana avisada uma vez só
        self.assertEqual(avisos.get().student, self.ana)

    def test_home_kpi_counts_students_without_photo(self):
        self.login(Role.SECRETARIA)
        self.assertEqual(self.client.get(reverse("home")).context["ws"]["students_without_photo"], 2)
