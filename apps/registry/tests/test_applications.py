"""Pré-cadastro pela família, análise da secretaria, configurações de cadastro
e envio de foto pela família (Prompt 14, rodadas 2 a 4)."""

import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear
from apps.communication.models import Notification
from apps.core.models import Role, School, User
from apps.core.navigation import all_visible_urls
from apps.registry.models import (
    Enrollment,
    GuardianLink,
    RegistrationSettings,
    Student,
    StudentApplication,
)
from apps.registry.tests.test_import import png_bytes

PW = "Senha-forte-123"


class AppBase(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        ctx = override_settings(MEDIA_ROOT=self.media)
        ctx.enable()
        self.addCleanup(ctx.disable)
        self.school = School.objects.create(name="Escola", code="e")
        self.year = SchoolYear.objects.create(school=self.school, name="2026", is_current=True)
        self.turma = ClassGroup.objects.create(school=self.school, school_year=self.year, name="1º A")
        self.sec = User.objects.create_user("sec", password=PW, role=Role.SECRETARIA, school=self.school)
        self.fam = User.objects.create_user("fam", password=PW, role=Role.RESPONSAVEL, school=self.school,
                                            first_name="Maria")
        self.other = User.objects.create_user("outra", password=PW, role=Role.RESPONSAVEL, school=self.school)
        self.cfg = RegistrationSettings.for_school(self.school)

    def login(self, user):
        self.client.logout()
        self.client.login(username=user.username, password=PW)

    def open_registration(self, **extra):
        self.cfg.family_mode = RegistrationSettings.MODE_FULL
        for k, v in extra.items():
            setattr(self.cfg, k, v)
        self.cfg.save()

    def fill_application(self):
        self.login(self.fam)
        self.client.post(reverse("application_start"))
        app = StudentApplication.objects.get(guardian=self.fam)
        self.client.post(reverse("application_step", args=[app.pk, 1]), {
            "first_name": "Lia", "last_name": "Souza", "birth_date": "2019-05-10",
            "desired_grade": "1º ano", "desired_turn": "manha", "nav": "next",
        })
        self.client.post(reverse("application_step", args=[app.pk, 2]), {
            "relation": "mae", "phone": "(11) 95555-4444", "nav": "next",
        })
        self.client.post(reverse("application_step", args=[app.pk, 3]), {
            "photo": SimpleUploadedFile("lia.png", png_bytes()), "nav": "next",
        })
        app.refresh_from_db()
        return app


class SettingsControlTests(AppBase):
    def test_default_is_off_and_hides_family_menu(self):
        self.login(self.fam)
        self.assertNotIn(reverse("family_applications"), all_visible_urls(self.fam))
        resp = self.client.post(reverse("application_start"))
        self.assertRedirects(resp, reverse("family_applications"))
        self.assertFalse(StudentApplication.objects.exists())
        self.assertContains(self.client.get(reverse("family_applications")), "feito pela secretaria")

    def test_full_mode_shows_menu_and_allows_start(self):
        self.open_registration()
        self.assertIn(reverse("family_applications"), all_visible_urls(self.fam))
        self.login(self.fam)
        self.client.post(reverse("application_start"))
        self.assertEqual(StudentApplication.objects.filter(guardian=self.fam).count(), 1)

    def test_closed_period_blocks_new_applications(self):
        self.open_registration(closes_on=timezone.localdate() - timedelta(days=1))
        self.login(self.fam)
        self.client.post(reverse("application_start"))
        self.assertFalse(StudentApplication.objects.exists())

    def test_settings_page_roles_and_audit(self):
        from apps.core.models import AuditLog

        for role, expected in ((Role.SECRETARIA, 200), (Role.DIRECAO, 200), (Role.ADMIN, 200),
                               (Role.PROFESSOR, 403), (Role.RESPONSAVEL, 403), (Role.COORDENACAO, 403)):
            u = User.objects.create_user(f"x-{role}", password=PW, role=role, school=self.school)
            self.login(u)
            self.assertEqual(self.client.get(reverse("registration_settings")).status_code, expected, role)
        self.login(self.sec)
        self.client.post(reverse("registration_settings"), {
            "family_mode": "foto", "family_fields": ["photo", "phone"], "allow_correction_requests": "on",
        })
        self.cfg.refresh_from_db()
        self.assertEqual((self.cfg.family_mode, self.cfg.fields_list), ("foto", ["photo", "phone"]))
        self.assertTrue(AuditLog.objects.filter(target_type="RegistrationSettings").exists())

    def test_disabled_fields_are_not_asked(self):
        self.open_registration(family_fields="photo")
        self.login(self.fam)
        self.client.post(reverse("application_start"))
        app = StudentApplication.objects.get()
        page = self.client.get(reverse("application_step", args=[app.pk, 2]))
        self.assertNotContains(page, 'name="phone"')
        page1 = self.client.get(reverse("application_step", args=[app.pk, 1]))
        self.assertNotContains(page1, 'name="desired_turn"')


class FamilyFlowTests(AppBase):
    def setUp(self):
        super().setUp()
        self.open_registration()

    def test_progress_is_saved_and_submit_notifies_secretaria(self):
        app = self.fill_application()
        self.assertEqual(app.status, "rascunho")
        self.assertEqual(app.first_name, "Lia")
        self.assertTrue(app.photo)
        self.assertEqual(app.step, 4)
        self.client.post(reverse("application_submit", args=[app.pk]))
        app.refresh_from_db()
        self.assertEqual(app.status, "enviado")
        self.assertTrue(Notification.objects.filter(user=self.sec, kind="cadastro").exists())
        self.assertFalse(Student.objects.exists())  # nada vira ficha sem aprovação
        # Enviado não é mais editável pela família.
        resp = self.client.post(reverse("application_step", args=[app.pk, 1]), {"first_name": "Outro"})
        self.assertRedirects(resp, reverse("application_view", args=[app.pk]))

    def test_submit_requires_minimum_data(self):
        self.login(self.fam)
        self.client.post(reverse("application_start"))
        app = StudentApplication.objects.get()
        self.client.post(reverse("application_submit", args=[app.pk]))
        app.refresh_from_db()
        self.assertEqual(app.status, "rascunho")

    def test_future_birth_date_refused(self):
        self.login(self.fam)
        self.client.post(reverse("application_start"))
        app = StudentApplication.objects.get()
        resp = self.client.post(reverse("application_step", args=[app.pk, 1]), {
            "first_name": "Lia", "birth_date": (timezone.localdate() + timedelta(days=3)).isoformat(),
            "desired_grade": "1º", "nav": "next"})
        self.assertContains(resp, "não pode ser futura")

    def test_other_family_cannot_see_or_edit(self):
        app = self.fill_application()
        self.login(self.other)
        for url in (reverse("application_step", args=[app.pk, 1]), reverse("application_view", args=[app.pk]),
                    reverse("application_photo", args=[app.pk])):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(self.client.post(reverse("application_submit", args=[app.pk])).status_code, 404)
        self.login(User.objects.create_user("prof", password=PW, role=Role.PROFESSOR, school=self.school))
        self.assertEqual(self.client.get(reverse("application_review", args=[app.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("application_photo", args=[app.pk])).status_code, 404)


class ReviewTests(AppBase):
    def setUp(self):
        super().setUp()
        self.open_registration()
        self.app = self.fill_application()
        self.client.post(reverse("application_submit", args=[self.app.pk]))
        self.login(self.sec)

    def test_approve_creates_student_link_and_optional_enrollment(self):
        self.client.post(reverse("application_review", args=[self.app.pk]), {
            "decision": "aprovar", "target": "nova", "class_group": self.turma.pk, "code": "R-1"})
        self.app.refresh_from_db()
        st = self.app.student
        self.assertEqual((self.app.status, st.first_name, st.code), ("aprovado", "Lia", "R-1"))
        self.assertTrue(st.photo)
        self.assertTrue(GuardianLink.objects.filter(guardian=self.fam, student=st, status="aprovado").exists())
        self.assertTrue(Enrollment.objects.filter(student=st, class_group=self.turma, status="ativo").exists())
        self.assertTrue(Notification.objects.filter(user=self.fam, kind="cadastro", student=st).exists())

    def test_approve_without_class_creates_no_enrollment(self):
        self.client.post(reverse("application_review", args=[self.app.pk]), {"decision": "aprovar", "target": "nova"})
        self.assertFalse(Enrollment.objects.exists())
        self.assertEqual(Student.objects.count(), 1)

    def test_existing_record_is_offered_and_reused(self):
        existing = Student.objects.create(school=self.school, first_name="Lia", last_name="Souza",
                                          birth_date=self.app.birth_date)
        page = self.client.get(reverse("application_review", args=[self.app.pk]))
        self.assertContains(page, "Já existe ficha")
        self.client.post(reverse("application_review", args=[self.app.pk]),
                         {"decision": "aprovar", "target": str(existing.pk)})
        self.assertEqual(Student.objects.count(), 1)
        self.assertTrue(GuardianLink.objects.filter(student=existing, guardian=self.fam).exists())

    def test_correction_needs_note_and_lets_family_edit_again(self):
        resp = self.client.post(reverse("application_review", args=[self.app.pk]), {"decision": "correcao"})
        self.assertContains(resp, "Explique à família")
        self.client.post(reverse("application_review", args=[self.app.pk]),
                         {"decision": "correcao", "note": "Envie a certidão."})
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "correcao")
        self.login(self.fam)
        page = self.client.get(reverse("application_step", args=[self.app.pk, 1]))
        self.assertContains(page, "Envie a certidão.")
        self.client.post(reverse("application_submit", args=[self.app.pk]))
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "enviado")

    def test_reject_and_no_second_decision(self):
        self.client.post(reverse("application_review", args=[self.app.pk]),
                         {"decision": "recusar", "note": "Sem vagas para o turno."})
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "recusado")
        self.client.post(reverse("application_review", args=[self.app.pk]), {"decision": "aprovar", "target": "nova"})
        self.assertFalse(Student.objects.exists())


class ChildPhotoTests(AppBase):
    def setUp(self):
        super().setUp()
        self.child = Student.objects.create(school=self.school, first_name="Teo", last_name="Lima",
                                            birth_date="2018-01-01", status="ativo")
        GuardianLink.objects.create(school=self.school, guardian=self.fam, student=self.child, status="aprovado")

    def test_photo_mode_changes_only_the_photo(self):
        self.cfg.family_mode = RegistrationSettings.MODE_PHOTO
        self.cfg.save()
        self.login(self.fam)
        self.assertContains(self.client.get(reverse("my_children")), "Enviar foto")
        self.client.post(reverse("child_photo", args=[self.child.pk]),
                         {"photo": SimpleUploadedFile("t.png", png_bytes()), "first_name": "Hacker"})
        self.child.refresh_from_db()
        self.assertTrue(self.child.photo)
        self.assertEqual(self.child.first_name, "Teo")

    def test_off_mode_and_other_family_are_refused(self):
        self.login(self.fam)
        self.assertNotContains(self.client.get(reverse("my_children")), "Enviar foto")
        self.assertEqual(self.client.get(reverse("child_photo", args=[self.child.pk])).status_code, 403)
        self.cfg.family_mode = RegistrationSettings.MODE_PHOTO
        self.cfg.save()
        self.login(self.other)
        self.assertEqual(self.client.get(reverse("child_photo", args=[self.child.pk])).status_code, 403)

    def test_correction_request_shortcut_prefills(self):
        self.login(self.fam)
        url = reverse("communication:request_create") + f"?categoria=cadastro&estudante={self.child.pk}"
        form = self.client.get(url).context["form"]
        self.assertEqual(form.initial, {"category": "cadastro", "student": self.child.pk})


class RetentionAndExportAuditTests(AppBase):
    def test_purge_removes_files_of_old_refused_applications_only(self):
        from datetime import timedelta

        from django.core.management import call_command
        from django.core.files.uploadedfile import SimpleUploadedFile as F

        from apps.registry.models import ApplicationDocument

        old = StudentApplication.objects.create(school=self.school, guardian=self.fam, status="recusado",
                                                first_name="Velho")
        ApplicationDocument.objects.create(application=old, kind="certidao", original_name="c.pdf",
                                           file=F("c.pdf", b"%PDF-1.4"))
        kept = StudentApplication.objects.create(school=self.school, guardian=self.fam, status="aprovado",
                                                 first_name="Aprovado")
        ApplicationDocument.objects.create(application=kept, kind="certidao", original_name="d.pdf",
                                           file=F("d.pdf", b"%PDF-1.4"))
        StudentApplication.objects.filter(pk__in=[old.pk, kept.pk]).update(
            updated_at=timezone.now() - timedelta(days=200))
        call_command("purgeapplications", "--simular")
        self.assertEqual(ApplicationDocument.objects.count(), 2)
        call_command("purgeapplications")
        self.assertEqual(list(ApplicationDocument.objects.values_list("application_id", flat=True)), [kept.pk])
        self.assertTrue(StudentApplication.objects.filter(pk=old.pk).exists())  # o pedido fica, sem arquivos

    def test_rejected_rows_download_is_audited(self):
        from apps.core.models import AuditLog
        from apps.registry.models import ImportBatch

        batch = ImportBatch.objects.create(school=self.school, filename="x.csv", rows="[]")
        self.login(self.sec)
        self.client.get(reverse("student_import_rejected", args=[batch.pk]))
        self.assertTrue(AuditLog.objects.filter(action="export", target_type="ImportBatch").exists())
