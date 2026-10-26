from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.core.models import Role, School
from apps.pedagogy.models import AbsenceJustification, Activity, AttendanceRecord, Evaluation
from apps.registry.models import Enrollment, GuardianLink, Student

from ..models import (
    Announcement,
    AnnouncementRead,
    Message,
    Notification,
    ServiceRequest,
    Thread,
)

User = get_user_model()


class CommunicationBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola A", code="a")
        self.school_b = School.objects.create(name="Escola B", code="b")
        pw = "senha-forte-1"
        self.admin = User.objects.create_user(
            username="adm", password=pw, role=Role.ADMIN, school=self.school
        )
        self.sec = User.objects.create_user(
            username="sec", password=pw, role=Role.SECRETARIA, school=self.school
        )
        self.coord = User.objects.create_user(
            username="coord", password=pw, role=Role.COORDENACAO, school=self.school
        )
        self.direc = User.objects.create_user(
            username="dir", password=pw, role=Role.DIRECAO, school=self.school
        )
        self.prof = User.objects.create_user(
            username="prof", password=pw, role=Role.PROFESSOR, school=self.school
        )
        self.other_prof = User.objects.create_user(
            username="prof_b", password=pw, role=Role.PROFESSOR, school=self.school_b
        )
        self.resp = User.objects.create_user(
            username="resp", password=pw, role=Role.RESPONSAVEL, school=self.school
        )
        self.resp_b = User.objects.create_user(
            username="resp_b", password=pw, role=Role.RESPONSAVEL, school=self.school_b
        )
        self.year = SchoolYear.objects.create(school=self.school, name="2026")
        self.turma = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="1º Ano A"
        )
        self.turma_b = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="1º Ano B"
        )
        self.mat = Subject.objects.create(school=self.school, name="Matemática")
        TeacherAssignment.objects.create(
            school=self.school,
            school_year=self.year,
            teacher=self.prof,
            class_group=self.turma,
            subject=self.mat,
        )
        self.ana = Student.objects.create(school=self.school, first_name="Ana")
        self.bea = Student.objects.create(school=self.school, first_name="Beatriz")
        Enrollment.objects.create(
            school=self.school, student=self.ana, class_group=self.turma, school_year=self.year
        )
        Enrollment.objects.create(
            school=self.school, student=self.bea, class_group=self.turma_b, school_year=self.year
        )
        GuardianLink.objects.create(
            school=self.school, guardian=self.resp, student=self.ana, status="aprovado"
        )

    def login(self, username):
        self.client.login(username=username, password="senha-forte-1")

    def make_evaluation(self):
        return Evaluation.objects.create(
            school=self.school,
            subject=self.mat,
            class_group=self.turma,
            title="Prova de Matemática",
            created_by=self.prof,
        )


class NotificationEventTests(CommunicationBase):
    def test_publishing_evaluation_notifies_guardian(self):
        ev = self.make_evaluation()
        self.login("prof")
        self.client.post(reverse("pedagogy:evaluation_publish", args=[ev.pk]))
        self.assertTrue(
            Notification.objects.filter(
                user=self.resp, kind="avaliacao", title__contains="Notas publicadas"
            ).exists()
        )

    def test_activity_publication_notifies_guardian(self):
        """Publicar avisa a família, e o aviso nomeia o estudante."""
        self.login("prof")
        self.client.post(
            reverse("pedagogy:activity_create"),
            {
                "class_group": self.turma.pk,
                "subject": self.mat.pk,
                "title": "Tarefa de casa",
                "description": "Resolver os exercícios 1 a 10.",
                "deadline": "2026-04-10",
                "criteria": "",
                "published_date": "2026-03-01",
                "_publish": "1",
            },
        )
        notif = Notification.objects.filter(
            user=self.resp, kind="atividade", title__contains="Tarefa de casa"
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn("Ana", notif.body)

    def test_activity_draft_does_not_notify_guardian(self):
        """Rascunho não avisa ninguém: nada foi publicado à família ainda."""
        self.login("prof")
        self.client.post(
            reverse("pedagogy:activity_create"),
            {
                "class_group": self.turma.pk,
                "subject": self.mat.pk,
                "title": "Ainda rascunho",
                "description": "Texto em elaboração.",
                "published_date": "2026-03-01",
            },
        )
        self.assertEqual(
            Notification.objects.filter(title__contains="Ainda rascunho").count(), 0
        )

    def test_justification_resolution_notifies_requester(self):
        just = AbsenceJustification.objects.create(
            school=self.school,
            student=self.ana,
            class_group=self.turma,
            start_date="2026-03-02",
            end_date="2026-03-03",
            reason="DoenÃ§a",
            submitted_by=self.resp,
        )
        self.login("sec")
        self.client.post(
            reverse("pedagogy:justification_resolve", args=[just.pk, "aprovar"]),
            {"note": "Atestado ok"},
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.resp, kind="justificativa", title__contains="aprovada"
            ).exists()
        )


class ThreadTests(CommunicationBase):
    def _make_thread(self):
        self.login("resp")
        self.client.post(
            reverse("communication:thread_create"),
            {
                "student": self.ana.pk,
                "recipient": self.prof.pk,
                "title": "Dúvida sobre o conteúdo",
                "body": "Boa tarde, nÃ£o entendi a tarefa.",
            },
        )
        return Thread.objects.get(title="Dúvida sobre o conteúdo")

    def test_responsavel_starts_thread_and_notifies_professional(self):
        thread = self._make_thread()
        self.assertEqual(thread.participants.count(), 2)
        message = Message.objects.filter(thread=thread).first()
        self.assertEqual(message.sender, self.resp)
        self.assertTrue(
            Notification.objects.filter(user=self.prof, kind="mensagem").exists()
        )

    def test_professional_replies_and_confirms_read(self):
        thread = self._make_thread()
        self.login("prof")
        self.client.post(
            reverse("communication:thread_detail", args=[thread.pk]),
            {"body": "Olá! Posso ajudar."},
        )
        message = Message.objects.filter(thread=thread, sender=self.prof).first()
        self.assertIsNotNone(message)
        self.assertTrue(
            Notification.objects.filter(user=self.resp, kind="mensagem").exists()
        )
        self.client.get(reverse("communication:thread_detail", args=[thread.pk]))
        resp_message = Message.objects.get(thread=thread, sender=self.resp)
        self.assertIsNotNone(resp_message.read_at)

    def test_thread_creation_blocks_responsavel_to_responsavel(self):
        self.login("resp")
        self.client.post(
            reverse("communication:thread_create"),
            {
                "recipient": self.resp_b.pk,
                "title": "Proibido",
                "body": "teste",
            },
        )
        self.assertFalse(Thread.objects.filter(title="Proibido").exists())

    def test_non_participant_cannot_view_thread(self):
        thread = self._make_thread()
        self.login("adm")
        self.assertEqual(
            self.client.get(
                reverse("communication:thread_detail", args=[thread.pk])
            ).status_code,
            403,
        )
        self.login("resp_b")
        self.assertEqual(
            self.client.get(
                reverse("communication:thread_detail", args=[thread.pk])
            ).status_code,
            404,
        )

    def test_cross_school_user_cannot_message(self):
        self.login("resp_b")
        self.client.post(
            reverse("communication:thread_create"),
            {
                "recipient": self.prof.pk,
                "title": "Interescola",
                "body": "x",
            },
        )
        self.assertFalse(Thread.objects.filter(title="Interescola").exists())


class AnnouncementTests(CommunicationBase):
    def _create(self, **overrides):
        data = {
            "scope": "institucional",
            "audience": "familia",
            "class_group": "",
            "student": "",
            "title": "Comunicado teste",
            "body": "Texto do comunicado.",
        }
        data.update(overrides)
        return self.client.post(reverse("communication:announcement_create"), data)

    def test_secretaria_cannot_create_institutional(self):
        self.login("sec")
        self.client.post(reverse("communication:announcement_create"), {})
        response = self._create()
        self.assertFalse(
            Announcement.objects.filter(title="Comunicado teste")
            .filter(created_by=self.sec)
            .exists()
        )
        self.assertEqual(response.status_code, 200)

    def test_direcao_creates_institutional_and_notifies_family(self):
        self.login("dir")
        response = self._create()
        ann = Announcement.objects.get(title="Comunicado teste")
        self.assertEqual(ann.scope, "institucional")
        self.assertTrue(
            Notification.objects.filter(
                user=self.resp, kind="comunicado", title__contains="Comunicado teste"
            ).exists()
        )
        self.assertEqual(response.status_code, 302)

    def test_professor_creates_turma_announcement_for_own_class(self):
        self.login("prof")
        response = self._create(
            scope="turma",
            class_group=self.turma.pk,
        )
        ann = Announcement.objects.get(title="Comunicado teste")
        self.assertEqual(ann.class_group, self.turma)
        self.assertEqual(response.status_code, 302)

    def test_professor_cannot_announce_other_class(self):
        self.login("prof")
        self._create(scope="turma", class_group=self.turma_b.pk)
        self.assertFalse(
            Announcement.objects.filter(title="Comunicado teste").exists()
        )

    def test_guardian_sees_only_children_announcements(self):
        self.login("dir")
        for_class = Announcement.objects.create(
            school=self.school,
            scope="turma",
            audience="familia",
            class_group=self.turma,
            title="Para turma A",
            body="x",
            created_by=self.direc,
        )
        other = Announcement.objects.create(
            school=self.school,
            scope="turma",
            audience="familia",
            class_group=self.turma_b,
            title="Para turma B",
            body="x",
            created_by=self.direc,
        )
        self.login("resp")
        response = self.client.get(reverse("communication:announcement_list"))
        self.assertContains(response, "Para turma A")
        self.assertNotContains(response, "Para turma B")
        self.assertEqual(response.status_code, 200)
        self.client.get(reverse("communication:announcement_detail", args=[for_class.pk]))
        self.assertTrue(
            AnnouncementRead.objects.filter(
                announcement=for_class, user=self.resp
            ).exists()
        )

    def test_cross_school_user_cannot_view_announcement(self):
        ann = Announcement.objects.create(
            school=self.school,
            scope="institucional",
            audience="todos",
            title="Institucional A",
            body="x",
            created_by=self.direc,
        )
        self.login("resp_b")
        self.assertEqual(
            self.client.get(
                reverse("communication:announcement_detail", args=[ann.pk])
            ).status_code,
            404,
        )


class ServiceRequestTests(CommunicationBase):
    def _create_request(self):
        self.login("resp")
        self.client.post(
            reverse("communication:request_create"),
            {
                "student": self.ana.pk,
                "category": "matricula",
                "title": "Atualizar endereço",
                "description": "Mudamos de endereço.",
            },
        )
        return ServiceRequest.objects.get(title="Atualizar endereço")

    def test_responsavel_creates_and_notifies_secretaria(self):
        req = self._create_request()
        self.assertEqual(req.status, "recebida")
        self.assertTrue(
            Notification.objects.filter(user=self.sec, kind="solicitacao").exists()
        )

    def test_responsavel_lists_only_own_requests(self):
        self._create_request()
        other = ServiceRequest.objects.create(
            school=self.school,
            requester=self.resp_b,
            title="De outro responsável",
            description="x",
        )
        self.login("resp")
        response = self.client.get(reverse("communication:request_list"))
        self.assertContains(response, "Atualizar endereço")
        self.assertNotContains(response, "De outro responsável")

    def test_professor_lists_only_own_students_requests(self):
        ServiceRequest.objects.create(
            school=self.school,
            requester=self.resp,
            student=self.ana,
            title="Da minha aluna",
            description="x",
        )
        ServiceRequest.objects.create(
            school=self.school,
            requester=self.resp,
            student=self.bea,
            title="De outra turma",
            description="x",
        )
        self.login("prof")
        response = self.client.get(reverse("communication:request_list"))
        self.assertContains(response, "Da minha aluna")
        self.assertNotContains(response, "De outra turma")

    def test_secretaria_resolves_and_notifies_requester(self):
        req = self._create_request()
        self.login("sec")
        self.client.post(
            reverse("communication:request_detail", args=[req.pk]),
            {"status": "respondida", "response": "Cadastro atualizado."},
        )
        req.refresh_from_db()
        self.assertEqual(req.status, "respondida")
        self.assertEqual(req.response, "Cadastro atualizado.")
        self.assertTrue(
            Notification.objects.filter(
                user=self.resp, kind="solicitacao", title__contains="atualizada"
            ).exists()
        )

    def test_responsavel_cannot_resolve(self):
        req = self._create_request()
        self.client.post(
            reverse("communication:request_detail", args=[req.pk]),
            {"status": "concluida", "response": "tentar"},
        )
        req.refresh_from_db()
        self.assertEqual(req.status, "recebida")

    def test_cross_school_cannot_view_request(self):
        req = self._create_request()
        self.login("resp_b")
        self.assertEqual(
            self.client.get(
                reverse("communication:request_detail", args=[req.pk])
            ).status_code,
            404,
        )
