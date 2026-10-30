"""Atividades com data de aplicação e fluxo de impressão (Prompt 14, rodada 8)."""

import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.communication.models import Notification
from apps.coordination.models import CoordinatorAssignment
from apps.core.models import Role, School, User
from apps.pedagogy.models import Activity
from apps.printing.models import PrintEvent, PrintRequest
from apps.registry.models import Enrollment, GuardianLink, Student

PW = "Senha-forte-123"


class PrintBase(TestCase):
    coordenacao_restrita = True

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        ctx = override_settings(MEDIA_ROOT=self.media)
        ctx.enable()
        self.addCleanup(ctx.disable)
        self.school = School.objects.create(name="Escola", code="e")
        year = SchoolYear.objects.create(school=self.school, name="2026", is_current=True)
        self.a = ClassGroup.objects.create(school=self.school, school_year=year, name="8º A")
        self.b = ClassGroup.objects.create(school=self.school, school_year=year, name="8º B")
        self.cien = Subject.objects.create(school=self.school, name="Ciências")
        mk = lambda u, r: User.objects.create_user(u, password=PW, role=r, school=self.school, first_name=u.title())
        self.prof = mk("prof", Role.PROFESSOR)
        self.outro = mk("outro", Role.PROFESSOR)
        self.coord_a = mk("coorda", Role.COORDENACAO)
        self.coord_b = mk("coordb", Role.COORDENACAO)
        self.sec = mk("sec", Role.SECRETARIA)
        self.fam = mk("fam", Role.RESPONSAVEL)
        TeacherAssignment.objects.create(school=self.school, school_year=year, teacher=self.prof,
                                         class_group=self.a, subject=self.cien)
        for coord, cg in ((self.coord_a, self.a), (self.coord_b, self.b)):
            d = CoordinatorAssignment.objects.create(school=self.school, coordinator=coord,
                                                     starts_on=timezone.localdate())
            d.class_groups.add(cg)
        for i in range(3):
            st = Student.objects.create(school=self.school, first_name=f"Aluno{i}")
            Enrollment.objects.create(school=self.school, student=st, class_group=self.a, school_year=year)
        GuardianLink.objects.create(school=self.school, guardian=self.fam, student=st, status="aprovado")
        self.app_day = timezone.localdate() + timedelta(days=7)
        self.act = Activity.objects.create(school=self.school, class_group=self.a, subject=self.cien,
                                           title="Ciclo da água", created_by=self.prof, status="publicada",
                                           class_date=self.app_day, internal_notes="Levar copos para a experiência")

    def login(self, user):
        self.client.logout()
        self.client.login(username=user.username, password=PW)

    def create_request(self, send=True, **extra):
        self.login(self.prof)
        data = {"atividade": self.act.pk, "application_date": self.app_day.isoformat(),
                "desired_date": (self.app_day - timedelta(days=1)).isoformat(), "copies": 3,
                "file": SimpleUploadedFile("ciclo.pdf", b"%PDF-1.4 conteudo"), "send": "1" if send else "0"}
        data.update(extra)
        resp = self.client.post(reverse("printing:create") + f"?atividade={self.act.pk}", data)
        self.form_errors = resp.context["form"].errors if resp.status_code == 200 else None
        return PrintRequest.objects.order_by("pk").last()


class ActivityFieldsTests(PrintBase):
    def test_application_date_required_and_internal_notes_hidden_from_family(self):
        self.login(self.prof)
        resp = self.client.post(reverse("pedagogy:activity_create"), {
            "class_group": self.a.pk, "subject": self.cien.pk, "title": "Sem data",
            "published_date": timezone.localdate().isoformat()})
        self.assertFalse(Activity.objects.filter(title="Sem data").exists())
        self.assertEqual(resp.status_code, 200)
        self.login(self.fam)
        page = self.client.get(reverse("pedagogy:activity_detail", args=[self.act.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Levar copos")
        self.login(self.prof)
        self.assertContains(self.client.get(reverse("pedagogy:activity_detail", args=[self.act.pk])), "Levar copos")

    def test_application_date_shows_in_calendar_for_staff(self):
        self.login(self.prof)
        page = self.client.get(reverse("school_calendar:calendar_index") + f"?start={self.app_day}&end={self.app_day}")
        self.assertContains(page, "Aplicação em aula")


class FlowTests(PrintBase):
    def test_full_flow_with_history_and_notifications(self):
        req = self.create_request()
        self.assertEqual((req.status, req.copies, req.submissions), ("enviada", 3, 1))
        # Só a coordenação que acompanha a turma recebe, com os dados pedidos.
        aviso = Notification.objects.get(user=self.coord_a, kind="impressao")
        for trecho in ("Prof", "Ciências", "8º A", "Cópias: 3", self.app_day.strftime("%d/%m/%Y")):
            self.assertIn(trecho, aviso.body)
        self.assertFalse(Notification.objects.filter(user=self.coord_b).exists())
        # Coordenação de outra turma não analisa nem pela URL.
        self.login(self.coord_b)
        self.assertEqual(self.client.get(reverse("printing:detail", args=[req.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("printing:act", args=[req.pk]), {"action": "approve"}).status_code, 403)
        self.login(self.coord_a)
        self.client.post(reverse("printing:act", args=[req.pk]), {"action": "approve"})
        req.refresh_from_db()
        self.assertEqual(req.status, "aguardando")
        self.assertTrue(Notification.objects.filter(user=self.sec, kind="impressao").exists())
        self.login(self.sec)
        for action in ("start", "printed", "ready", "deliver"):
            self.client.post(reverse("printing:act", args=[req.pk]), {"action": action})
        req.refresh_from_db()
        self.assertEqual(req.status, "entregue")
        self.assertEqual(list(PrintEvent.objects.filter(request=req).values_list("to_status", flat=True)),
                         ["enviada", "aguardando", "imprimindo", "impressa", "retirada", "entregue"])
        self.assertTrue(Notification.objects.filter(user=self.prof, kind="impressao", title__contains="Entregue").exists())

    def test_correction_and_reject_need_justification(self):
        req = self.create_request()
        self.login(self.coord_a)
        self.client.post(reverse("printing:act", args=[req.pk]), {"action": "correction"})
        req.refresh_from_db()
        self.assertEqual(req.status, "enviada")
        self.client.post(reverse("printing:act", args=[req.pk]), {"action": "correction", "note": "Arquivo cortado."})
        req.refresh_from_db()
        self.assertEqual((req.status, req.decision_note), ("correcao", "Arquivo cortado."))
        # Professor corrige e reenvia: nova notificação (sem duplicar a anterior).
        self.login(self.prof)
        self.client.post(reverse("printing:act", args=[req.pk]), {"action": "submit"})
        req.refresh_from_db()
        self.assertEqual((req.status, req.submissions), ("enviada", 2))
        self.assertEqual(Notification.objects.filter(user=self.coord_a, kind="impressao").count(), 2)

    def test_wrong_steps_and_roles_are_refused(self):
        req = self.create_request()
        self.login(self.sec)  # secretaria não imprime antes da aprovação
        self.assertEqual(self.client.post(reverse("printing:act", args=[req.pk]), {"action": "start"}).status_code, 403)
        self.login(self.outro)  # professor sem a turma
        self.assertEqual(self.client.get(reverse("printing:detail", args=[req.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("printing:file", args=[req.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("printing:create") + f"?atividade={self.act.pk}").status_code, 403)
        self.login(self.fam)
        self.assertEqual(self.client.get(reverse("printing:queue")).status_code, 403)

    def test_defaults_priority_and_validation(self):
        self.login(self.prof)
        form = self.client.get(reverse("printing:create") + f"?atividade={self.act.pk}").context["form"]
        self.assertEqual(form.initial["copies"], 3)  # estudantes ativos da turma
        near = timezone.localdate() + timedelta(days=1)
        req = self.create_request(application_date=near.isoformat(), desired_date=timezone.localdate().isoformat())
        self.assertEqual(req.priority, "alta")
        before = PrintRequest.objects.count()
        self.create_request(desired_date=(self.app_day + timedelta(days=1)).isoformat())
        self.assertEqual(PrintRequest.objects.count(), before)  # impressão depois da aplicação: recusado

    def test_queue_lists_by_scope(self):
        self.create_request()
        self.login(self.coord_a)
        self.assertContains(self.client.get(reverse("printing:queue")), "Ciclo da água")
        self.login(self.coord_b)
        self.assertNotContains(self.client.get(reverse("printing:queue")), "Ciclo da água")
        self.login(self.coord_a)
        self.assertContains(self.client.get(reverse("coordination:panel")), "Impressões a analisar")

