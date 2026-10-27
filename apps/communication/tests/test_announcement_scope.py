"""Quem vê e quem é avisado de cada comunicado.

Dois vazamentos corrigidos aqui:

1. A conta de estudante, criada depois do módulo de comunicação, não tinha
   regra própria: via todos os comunicados da escola — inclusive os
   individuais sobre colegas e os dirigidos só à equipe.
2. Com público "todos", a notificação ignorava a abrangência: um comunicado
   individual sobre um estudante avisava todas as famílias da escola, com o
   começo do texto na própria notificação.
"""

from django.urls import reverse

from apps.core.models import Role
from apps.registry.models import Enrollment, GuardianLink, Student

from ..access import announcement_recipients, can_view_announcement
from ..models import Announcement, Notification
from .test_communication import CommunicationBase, User

A = Announcement.Audience
S = Announcement.Scope


class AnnouncementScopeBase(CommunicationBase):
    def setUp(self):
        super().setUp()
        pw = "senha-forte-1"
        # Conta de estudante da Ana (turma A) e família da Beatriz (turma B).
        self.conta_ana = User.objects.create_user(
            username="aluno_ana", password=pw, role=Role.ESTUDANTE, school=self.school
        )
        self.ana.user = self.conta_ana
        self.ana.save(update_fields=["user"])
        self.resp_bea = User.objects.create_user(
            username="resp_bea", password=pw, role=Role.RESPONSAVEL, school=self.school
        )
        GuardianLink.objects.create(
            school=self.school, guardian=self.resp_bea, student=self.bea, status="aprovado"
        )
        self.conta_bea = User.objects.create_user(
            username="aluno_bea", password=pw, role=Role.ESTUDANTE, school=self.school
        )
        self.bea.user = self.conta_bea
        self.bea.save(update_fields=["user"])

    def ann(self, scope, audience, **extra):
        return Announcement.objects.create(
            school=self.school, scope=scope, audience=audience,
            title=f"{scope}-{audience}", body="Texto reservado.",
            created_by=self.coord, **extra,
        )


class StudentAccountTests(AnnouncementScopeBase):
    def test_student_sees_only_what_is_addressed_to_them(self):
        visiveis = [
            self.ann(S.INSTITUCIONAL, A.TODOS),
            self.ann(S.INSTITUCIONAL, A.FAMILIA),
            self.ann(S.TURMA, A.FAMILIA, class_group=self.turma),
        ]
        ocultos = [
            self.ann(S.INSTITUCIONAL, A.EQUIPE),
            self.ann(S.TURMA, A.FAMILIA, class_group=self.turma_b),
            self.ann(S.INDIVIDUAL, A.FAMILIA, student=self.bea),
            self.ann(S.INDIVIDUAL, A.TODOS, student=self.bea),
            # Individual sobre ela mesma: dirigido aos responsáveis.
            self.ann(S.INDIVIDUAL, A.FAMILIA, student=self.ana),
            self.ann(S.INDIVIDUAL, A.EQUIPE, student=self.ana),
        ]
        self.login("aluno_ana")
        resp = self.client.get(reverse("communication:announcement_list"))
        self.assertEqual(
            {a.pk for a in resp.context["announcements"]}, {a.pk for a in visiveis}
        )
        for a in ocultos:
            with self.subTest(comunicado=a.title):
                r = self.client.get(
                    reverse("communication:announcement_detail", args=[a.pk])
                )
                self.assertEqual(r.status_code, 403)

    def test_own_record_does_not_show_team_notes(self):
        self.ann(S.INDIVIDUAL, A.EQUIPE, student=self.ana)
        self.login("aluno_ana")
        resp = self.client.get(reverse("student_detail", args=[self.ana.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(resp.context["comm_announcements"]), [])
        self.assertNotContains(resp, "individual-equipe")


class RecipientTests(AnnouncementScopeBase):
    def recipients(self, ann):
        return set(announcement_recipients(ann))

    def test_individual_for_everyone_reaches_only_that_student(self):
        ann = self.ann(S.INDIVIDUAL, A.TODOS, student=self.bea)
        quem = self.recipients(ann)
        self.assertIn(self.resp_bea, quem)
        self.assertNotIn(self.resp, quem)  # família de outra estudante
        self.assertNotIn(self.conta_ana, quem)
        self.assertNotIn(self.conta_bea, quem)  # individual: só responsáveis
        self.assertNotIn(self.prof, quem)  # não leciona para a Beatriz
        self.assertIn(self.sec, quem)
        self.assertNotIn(self.coord, quem)  # quem publicou

    def test_class_announcement_reaches_class_only(self):
        ann = self.ann(S.TURMA, A.TODOS, class_group=self.turma)
        quem = self.recipients(ann)
        self.assertTrue({self.resp, self.conta_ana, self.prof} <= quem)
        self.assertFalse({self.resp_bea, self.conta_bea} & quem)

    def test_institutional_family_reaches_families_not_staff(self):
        ann = self.ann(S.INSTITUCIONAL, A.FAMILIA)
        quem = self.recipients(ann)
        self.assertTrue({self.resp, self.resp_bea, self.conta_ana, self.conta_bea} <= quem)
        self.assertFalse({self.prof, self.sec} & quem)
        self.assertNotIn(self.resp_b, quem)  # outra escola

    def test_everyone_notified_can_open_it(self):
        """Avisar e poder abrir são a mesma regra."""
        casos = [
            self.ann(S.INSTITUCIONAL, A.TODOS),
            self.ann(S.INSTITUCIONAL, A.EQUIPE),
            self.ann(S.TURMA, A.FAMILIA, class_group=self.turma),
            self.ann(S.TURMA, A.EQUIPE, class_group=self.turma_b),
            self.ann(S.INDIVIDUAL, A.FAMILIA, student=self.ana),
            self.ann(S.INDIVIDUAL, A.TODOS, student=self.bea),
        ]
        for ann in casos:
            for u in self.recipients(ann):
                with self.subTest(comunicado=ann.title, usuario=u.username):
                    self.assertTrue(can_view_announcement(u, ann))

    def test_publishing_through_the_screen_uses_the_rule(self):
        self.login("sec")
        self.client.post(
            reverse("communication:announcement_create"),
            {
                "scope": S.INDIVIDUAL, "audience": A.TODOS, "student": self.bea.pk,
                "title": "Sobre a Beatriz", "body": "Assunto da família.",
            },
        )
        ann = Announcement.objects.get(title="Sobre a Beatriz")
        avisados = set(
            Notification.objects.filter(title__contains="Sobre a Beatriz").values_list(
                "user__username", flat=True
            )
        )
        self.assertIn("resp_bea", avisados)
        self.assertNotIn("resp", avisados)
        self.assertNotIn("aluno_ana", avisados)
        n = Notification.objects.filter(user=self.resp_bea, title__contains="Sobre a Beatriz").get()
        self.assertEqual(n.url, reverse("communication:announcement_detail", args=[ann.pk]))


class TeacherScopeTests(AnnouncementScopeBase):
    def test_teacher_does_not_see_individual_of_other_class(self):
        outro = self.ann(S.INDIVIDUAL, A.TODOS, student=self.bea)
        proprio = self.ann(S.INDIVIDUAL, A.EQUIPE, student=self.ana)
        self.assertFalse(can_view_announcement(self.prof, outro))
        self.assertTrue(can_view_announcement(self.prof, proprio))
