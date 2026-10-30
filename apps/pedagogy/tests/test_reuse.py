"""Banco de atividades: reutilizar o que o professor já preparou."""

import shutil
import tempfile
from datetime import timedelta

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.core.models import AuditLog, Role, School, User
from apps.pedagogy.models import Activity, ActivityAttachment

PW = "Senha-forte-123"
MEDIA = tempfile.mkdtemp(prefix="escola-test-reuse-")


@override_settings(MEDIA_ROOT=MEDIA)
class ReuseTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        old = SchoolYear.objects.create(school=self.school, name="2025")
        cur = SchoolYear.objects.create(school=self.school, name="2026", is_current=True)
        self.old_cg = ClassGroup.objects.create(school=self.school, school_year=old, name="6º A")
        self.cg = ClassGroup.objects.create(school=self.school, school_year=cur, name="7º A")
        self.other_cg = ClassGroup.objects.create(school=self.school, school_year=cur, name="7º B")
        self.geo = Subject.objects.create(school=self.school, name="Geografia")
        mk = lambda u, r: User.objects.create_user(u, password=PW, role=r, school=self.school)
        self.prof = mk("prof", Role.PROFESSOR)
        self.colega = mk("colega", Role.PROFESSOR)
        TeacherAssignment.objects.create(school=self.school, school_year=cur, teacher=self.prof,
                                         class_group=self.cg, subject=self.geo)
        TeacherAssignment.objects.create(school=self.school, school_year=cur, teacher=self.colega,
                                         class_group=self.other_cg, subject=self.geo)
        day = timezone.localdate() - timedelta(days=300)
        # Atividade do ano passado, numa turma em que o professor não leciona mais.
        self.old = Activity.objects.create(
            school=self.school, class_group=self.old_cg, subject=self.geo, title="Mapa do bairro",
            description="Desenhe o caminho até a escola", content="Cartografia", objective="Ler mapas",
            internal_notes="Levar papel quadriculado", work_mode="grupo", published_date=day, deadline=day,
            class_date=day, created_by=self.prof, status="publicada", notified_at=timezone.now())
        ActivityAttachment.objects.create(activity=self.old, file=ContentFile(b"%PDF-1.4 mapa", name="mapa.pdf"),
                                          original_name="mapa.pdf", size=13, uploaded_by=self.prof)
        self.alheia = Activity.objects.create(
            school=self.school, class_group=self.other_cg, subject=self.geo, title="Do colega",
            description="x", published_date=day, created_by=self.colega)
        self.client.login(username="prof", password=PW)

    def test_bank_lists_own_activities_from_any_year_only(self):
        r = self.client.get(reverse("pedagogy:activity_bank"))
        self.assertContains(r, "Mapa do bairro")
        self.assertContains(r, "6º A · 2025")
        self.assertNotContains(r, "Do colega")
        r = self.client.get(reverse("pedagogy:activity_bank"), {"q": "cartografia"})
        self.assertEqual([a.pk for a in r.context["acts"]], [self.old.pk])
        # A ficha da atividade antiga (com estudantes e entregas) continua fechada.
        self.assertEqual(self.client.get(reverse("pedagogy:activity_detail", args=[self.old.pk])).status_code, 403)

    def test_reuse_creates_draft_with_text_and_attachment_copy(self):
        app = timezone.localdate() + timedelta(days=3)
        r = self.client.post(reverse("pedagogy:activity_reuse", args=[self.old.pk]), {
            "pair": f"{self.cg.pk}:{self.geo.pk}", "class_date": app.isoformat(), "copy_attachments": "on"})
        copy = Activity.objects.exclude(pk__in=[self.old.pk, self.alheia.pk]).get()
        self.assertRedirects(r, reverse("pedagogy:activity_edit", args=[copy.pk]))
        self.assertEqual(
            (copy.status, copy.class_group, copy.class_date, copy.deadline, copy.title, copy.work_mode,
             copy.content, copy.internal_notes, copy.notified_at),
            ("rascunho", self.cg, app, None, "Mapa do bairro", "grupo", "Cartografia", "Levar papel quadriculado",
             None))
        att = copy.attachments.get()
        old_att = self.old.attachments.get()
        self.assertNotEqual(att.file.name, old_att.file.name)  # arquivo próprio, não compartilhado
        with att.file.open("rb") as fh:
            self.assertEqual(fh.read(), b"%PDF-1.4 mapa")
        self.assertTrue(AuditLog.objects.filter(detail__startswith="Reutilizou").exists())

    def test_forged_pair_colleague_activity_and_other_roles(self):
        before = Activity.objects.count()
        r = self.client.post(reverse("pedagogy:activity_reuse", args=[self.old.pk]), {
            "pair": f"{self.other_cg.pk}:{self.geo.pk}", "class_date": "2026-11-10"})
        self.assertEqual(r.status_code, 200)  # turma de outro professor não está nas opções
        self.assertEqual(self.client.get(reverse("pedagogy:activity_reuse", args=[self.alheia.pk])).status_code, 403)
        self.assertEqual(Activity.objects.count(), before)
        for role in (Role.COORDENACAO, Role.SECRETARIA, Role.RESPONSAVEL):
            User.objects.create_user(f"x{role}", password=PW, role=role, school=self.school)
            self.client.login(username=f"x{role}", password=PW)
            self.assertEqual(self.client.get(reverse("pedagogy:activity_bank")).status_code, 403, role)
