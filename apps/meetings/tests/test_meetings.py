"""Reuniões e atendimentos: fluxo completo, privacidade e escopo."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.communication.models import Notification
from apps.coordination.models import CoordinatorAssignment
from apps.core.models import AuditLog, Role, School, User
from apps.registry.models import Enrollment, GuardianLink, Student

from ..models import Meeting, MeetingFollowUp
from ..services import meeting_reminders

PW = "senha-forte-1"


class MeetingBase(TestCase):
    coordenacao_restrita = True

    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        other = School.objects.create(name="Outra", code="o")
        year = SchoolYear.objects.create(school=self.school, name="2026", is_current=True)
        self.a = ClassGroup.objects.create(school=self.school, school_year=year, name="4º A")
        self.b = ClassGroup.objects.create(school=self.school, school_year=year, name="4º B")
        mat = Subject.objects.create(school=self.school, name="Matemática")
        mk = lambda u, r, s=self.school: User.objects.create_user(u, password=PW, role=r, school=s,
                                                                   first_name=u.title())
        self.prof = mk("prof", Role.PROFESSOR)
        self.prof2 = mk("prof2", Role.PROFESSOR)
        self.sec = mk("sec", Role.SECRETARIA)
        self.dir = mk("dir", Role.DIRECAO)
        self.adm = mk("adm", Role.ADMIN)
        self.coord = mk("coord", Role.COORDENACAO)
        self.resp = mk("resp", Role.RESPONSAVEL)
        self.resp2 = mk("resp2", Role.RESPONSAVEL)
        self.outsider = mk("fora", Role.DIRECAO, other)
        TeacherAssignment.objects.create(school=self.school, school_year=year, teacher=self.prof,
                                         class_group=self.a, subject=mat)
        TeacherAssignment.objects.create(school=self.school, school_year=year, teacher=self.prof2,
                                         class_group=self.b, subject=mat)
        self.ana = Student.objects.create(school=self.school, first_name="Ana")
        self.bea = Student.objects.create(school=self.school, first_name="Bea")
        Enrollment.objects.create(school=self.school, student=self.ana, class_group=self.a, school_year=year)
        Enrollment.objects.create(school=self.school, student=self.bea, class_group=self.b, school_year=year)
        GuardianLink.objects.create(school=self.school, guardian=self.resp, student=self.ana, status="aprovado")
        GuardianLink.objects.create(school=self.school, guardian=self.resp2, student=self.bea, status="aprovado")
        self.when = timezone.localtime(timezone.now() + timedelta(days=3)).replace(
            hour=14, minute=0, second=0, microsecond=0)

    def login(self, user):
        self.client.logout()
        self.client.login(username=user.username, password=PW)

    def create(self, user=None, **extra):
        self.login(user or self.prof)
        data = {"kind": "familia", "title": "Conversa sobre leitura", "student": self.ana.pk,
                "scheduled_at": f"{self.when:%Y-%m-%dT%H:%M}", "location": "Sala 3",
                "agenda": "Rotina de leitura em casa.", "invite_guardians": "on"}
        data.update(extra)
        resp = self.client.post(reverse("meetings:create"), data)
        return resp, Meeting.objects.order_by("-pk").first()


class MeetingFlowTests(MeetingBase):
    def test_teacher_schedules_and_family_is_notified(self):
        resp, m = self.create(staff=[self.sec.pk])
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(set(m.participants.all()), {self.prof, self.sec, self.resp})
        avisos = Notification.objects.filter(kind=Notification.Kind.MEETING)
        self.assertEqual(set(avisos.values_list("user", flat=True)), {self.sec.pk, self.resp.pk})
        aviso = avisos.get(user=self.resp)
        self.assertNotIn("leitura em casa", aviso.body)  # a pauta não vai no aviso
        self.assertTrue(AuditLog.objects.filter(action="create", target_type="Meeting").exists())

    def test_teacher_cannot_link_student_of_another_class(self):
        resp, m = self.create(student=self.bea.pk)
        self.assertEqual(resp.status_code, 200)  # formulário com erro
        self.assertIsNone(m)

    def test_guardians_require_a_student(self):
        resp, m = self.create(student="")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("invite_guardians", resp.context["form"].errors)

    def test_meeting_cannot_be_recorded_before_it_happens(self):
        _, m = self.create()  # daqui a 3 dias
        self.client.post(reverse("meetings:record", args=[m.pk]), {"summary": "Antes da hora"})
        m.refresh_from_db()
        self.assertEqual((m.status, m.summary), (Meeting.Status.SCHEDULED, ""))

    def test_family_sees_summary_but_never_staff_notes(self):
        ontem = timezone.localtime(timezone.now() - timedelta(days=1))
        _, m = self.create(scheduled_at=f"{ontem:%Y-%m-%dT%H:%M}")
        self.client.post(reverse("meetings:record", args=[m.pk]), {
            "summary": "Combinamos 15 minutos de leitura por dia.",
            "confidential_notes": "Avaliar encaminhamento ao serviço de psicologia."})
        self.client.post(reverse("meetings:follow_up_add", args=[m.pk]), {
            "description": "Enviar lista de livros", "responsible": self.prof.pk})
        self.client.post(reverse("meetings:follow_up_add", args=[m.pk]), {
            "description": "Acionar a rede de proteção", "staff_only": "on"})
        m.refresh_from_db()
        self.assertEqual(m.status, Meeting.Status.DONE)
        self.login(self.resp)
        page = self.client.get(reverse("meetings:detail", args=[m.pk]))
        self.assertContains(page, "Combinamos 15 minutos")
        self.assertContains(page, "Enviar lista de livros")
        self.assertNotContains(page, "psicologia")
        self.assertNotContains(page, "rede de proteção")
        self.assertNotContains(page, "Registrar a reunião")
        # Equipe participante vê tudo.
        self.login(self.prof)
        page = self.client.get(reverse("meetings:detail", args=[m.pk]))
        self.assertContains(page, "psicologia")
        self.assertContains(page, "rede de proteção")

    def test_other_family_and_other_school_are_refused(self):
        _, m = self.create()
        for user in (self.resp2, self.prof2, self.adm, self.outsider):
            self.login(user)
            self.assertIn(self.client.get(reverse("meetings:detail", args=[m.pk])).status_code, (403, 404),
                          user.username)
        GuardianLink.objects.filter(guardian=self.resp).update(status="pendente")
        self.login(self.resp)
        self.assertEqual(self.client.get(reverse("meetings:detail", args=[m.pk])).status_code, 403)

    def test_only_managers_change_the_meeting(self):
        _, m = self.create(staff=[self.sec.pk])
        for user in (self.sec, self.resp):  # participantes, mas não quem marcou
            self.login(user)
            self.assertEqual(self.client.get(reverse("meetings:edit", args=[m.pk])).status_code, 403)
            self.assertEqual(self.client.post(reverse("meetings:record", args=[m.pk]),
                                              {"summary": "x"}).status_code, 403)
        self.login(self.dir)
        self.assertEqual(self.client.get(reverse("meetings:edit", args=[m.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("meetings:record", args=[m.pk])).status_code, 403)  # só POST

    def test_follow_up_responsible_is_notified_and_concludes(self):
        _, m = self.create()
        self.client.post(reverse("meetings:follow_up_add", args=[m.pk]), {
            "description": "Separar livros", "responsible": self.sec.pk,
            "due_date": f"{timezone.localdate() + timedelta(days=5):%Y-%m-%d}"})
        fu = MeetingFollowUp.objects.get()
        self.assertTrue(Notification.objects.filter(user=self.sec, title__contains="Separar livros").exists())
        # A secretaria não estava na reunião; como responsável, passa a participar.
        self.assertIn(self.sec, fu.meeting.participants.all())
        self.login(self.sec)
        self.assertContains(self.client.get(reverse("meetings:list")), "Separar livros")
        resp = self.client.post(reverse("meetings:follow_up_update", args=[m.pk, fu.pk]),
                                {"status": "concluido", "done_note": "Entregues"})
        self.assertEqual(resp.status_code, 302)
        fu.refresh_from_db()
        self.assertEqual(fu.status, MeetingFollowUp.Status.DONE)
        self.assertEqual(fu.done_by, self.sec)
        self.login(self.prof2)
        self.assertEqual(self.client.post(reverse("meetings:follow_up_update", args=[m.pk, fu.pk]),
                                          {"status": "cancelado"}).status_code, 403)

    def test_cancel_notifies_and_locks(self):
        _, m = self.create()
        resp = self.client.post(reverse("meetings:cancel", args=[m.pk]), {"reason": "Professor em formação"})
        self.assertEqual(resp.status_code, 302)
        m.refresh_from_db()
        self.assertEqual(m.status, Meeting.Status.CANCELED)
        self.assertTrue(Notification.objects.filter(user=self.resp, title__startswith="Reunião cancelada").exists())
        resp = self.client.get(reverse("meetings:edit", args=[m.pk]))
        self.assertEqual(resp.status_code, 302)

    def test_reschedule_notifies_again_but_plain_edit_does_not(self):
        _, m = self.create()
        base = {"kind": "familia", "title": "Conversa sobre leitura", "student": self.ana.pk,
                "location": "Sala 3", "agenda": "x", "invite_guardians": "on"}
        url = reverse("meetings:edit", args=[m.pk])
        self.client.post(url, {**base, "scheduled_at": f"{self.when:%Y-%m-%dT%H:%M}"})
        self.assertEqual(Notification.objects.filter(user=self.resp).count(), 1)
        nova = self.when + timedelta(days=1)
        self.client.post(url, {**base, "scheduled_at": f"{nova:%Y-%m-%dT%H:%M}"})
        self.assertTrue(Notification.objects.filter(user=self.resp, title__startswith="Reunião remarcada").exists())

    def test_reminder_goes_once_the_day_before(self):
        amanha = timezone.localtime(timezone.now() + timedelta(days=1)).replace(hour=23, minute=0)
        _, m = self.create(scheduled_at=f"{amanha:%Y-%m-%dT%H:%M}")
        self.assertEqual(meeting_reminders(), 2)  # prof e resp
        self.assertEqual(meeting_reminders(), 0)
        self.assertTrue(Notification.objects.filter(user=self.resp, title__startswith="Lembrete").exists())

    def test_calendar_and_dashboard_timeline(self):
        _, m = self.create()
        self.login(self.resp)
        start = timezone.localdate()
        cal = self.client.get(reverse("school_calendar:calendar_index"),
                              {"start": f"{start:%Y-%m-%d}", "end": f"{start + timedelta(days=10):%Y-%m-%d}"})
        self.assertContains(cal, "Conversa sobre leitura")
        dash = self.client.get(reverse("analytics:student_dashboard", args=[self.ana.pk]),
                               {"periodo": "personalizado", "inicio": f"{start:%Y-%m-%d}",
                                "fim": f"{start + timedelta(days=10):%Y-%m-%d}"})
        self.assertContains(dash, "Conversa sobre leitura")
        self.login(self.resp2)
        cal = self.client.get(reverse("school_calendar:calendar_index"),
                              {"start": f"{start:%Y-%m-%d}", "end": f"{start + timedelta(days=10):%Y-%m-%d}"})
        self.assertNotContains(cal, "Conversa sobre leitura")


class MeetingScopeTests(MeetingBase):
    def test_direction_sees_all_and_restricted_coordination_only_its_classes(self):
        _, m = self.create()
        self.login(self.dir)
        self.assertEqual(self.client.get(reverse("meetings:detail", args=[m.pk])).status_code, 200)
        d = CoordinatorAssignment.objects.create(school=self.school, coordinator=self.coord,
                                                 starts_on=timezone.localdate())
        d.class_groups.add(self.b)
        self.login(self.coord)
        self.assertEqual(self.client.get(reverse("meetings:detail", args=[m.pk])).status_code, 403)
        form = self.client.get(reverse("meetings:create")).context["form"]
        self.assertEqual(list(form.fields["student"].queryset), [self.bea])
        d.class_groups.add(self.a)
        self.login(self.coord)
        self.assertEqual(self.client.get(reverse("meetings:detail", args=[m.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("meetings:edit", args=[m.pk])).status_code, 200)

    def test_admin_has_no_meetings_menu_and_no_access(self):
        from apps.core.navigation import all_visible_urls

        self.assertNotIn(reverse("meetings:list"), all_visible_urls(self.adm))
        self.assertIn(reverse("meetings:list"), all_visible_urls(self.resp))
        self.login(self.adm)
        self.assertEqual(self.client.get(reverse("meetings:list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("meetings:create")).status_code, 403)


class HomonymTests(MeetingBase):
    def test_homonyms_are_told_apart_by_class(self):
        """Duas estudantes com o mesmo nome: a lista diz a turma de cada uma."""
        Student.objects.filter(pk=self.bea.pk).update(first_name="Ana")
        TeacherAssignment.objects.create(school=self.school, school_year=self.a.school_year,
                                         teacher=self.prof, class_group=self.b,
                                         subject=Subject.objects.get(name="Matemática"))
        self.login(self.prof)
        html = self.client.get(reverse("meetings:create")).content.decode()
        self.assertIn("Ana — 4º A", html)
        self.assertIn("Ana — 4º B", html)
        self.login(self.coord)
        CoordinatorAssignment.objects.create(school=self.school, coordinator=self.coord,
                                             starts_on=timezone.localdate(), all_school=True)
        html = self.client.get(reverse("pedagogy:occurrence_create")).content.decode()
        self.assertIn("Ana — 4º B", html)
