"""Avisos automáticos à família, regras da escola, preferências e e-mail (Prompt 14, rodada 9)."""

from datetime import date, timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.communication.models import Notification, NotificationMute, NotificationRule
from apps.core.models import Role, School, User
from apps.pedagogy.models import Activity, AttendanceRecord, Evaluation, Grade, PedagogicalObservation
from apps.registry.models import Enrollment, GuardianLink, GuardianProfile, Student

PW = "Senha-forte-123"


class FamBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        year = SchoolYear.objects.create(school=self.school, name="2026", is_current=True)
        self.cg = ClassGroup.objects.create(school=self.school, school_year=year, name="4º A")
        self.mat = Subject.objects.create(school=self.school, name="Matemática")
        mk = lambda u, r: User.objects.create_user(u, password=PW, role=r, school=self.school, first_name=u.title(),
                                                   email=f"{u}@x.com")
        self.prof = mk("prof", Role.PROFESSOR)
        self.fam = mk("fam", Role.RESPONSAVEL)
        self.outra = mk("outra", Role.RESPONSAVEL)
        self.dir = mk("dir", Role.DIRECAO)
        TeacherAssignment.objects.create(school=self.school, school_year=year, teacher=self.prof,
                                         class_group=self.cg, subject=self.mat)
        self.ana = Student.objects.create(school=self.school, first_name="Ana")
        self.bia = Student.objects.create(school=self.school, first_name="Bia")
        for s in (self.ana, self.bia):
            Enrollment.objects.create(school=self.school, student=s, class_group=self.cg, school_year=year)
        GuardianLink.objects.create(school=self.school, guardian=self.fam, student=self.ana, status="aprovado")
        GuardianLink.objects.create(school=self.school, guardian=self.outra, student=self.bia, status="aprovado")

    def login(self, user):
        self.client.logout()
        self.client.login(username=user.username, password=PW)

    def fam_notes(self, user=None):
        return Notification.objects.filter(user=user or self.fam)


class EventTests(FamBase):
    def test_grade_changed_after_publication_notifies_only_that_family(self):
        ev = Evaluation.objects.create(school=self.school, subject=self.mat, class_group=self.cg, title="Prova 1",
                                       date=date(2026, 3, 10), created_by=self.prof, status="publicada")
        Grade.objects.create(school=self.school, evaluation=ev, student=self.ana, value=5)
        self.login(self.prof)
        self.client.post(reverse("pedagogy:evaluation_grade", args=[ev.pk]),
                         {f"grade_{self.ana.pk}": "7", f"grade_{self.bia.pk}": ""})
        n = self.fam_notes().get(kind="nota")
        self.assertEqual((n.student, n.title), (self.ana, "Nota alterada: Prova 1"))
        self.assertFalse(self.fam_notes(self.outra).exists())  # nenhum dado de outra família

    def test_absence_registered_and_corrected(self):
        self.login(self.prof)
        today = timezone.localdate().isoformat()
        url = reverse("pedagogy:attendance_register", args=[self.cg.pk]) + f"?data={today}"
        page = self.client.get(url)
        form = page.context["form"]
        data = {"date": today}
        for st, name in form.rows:
            data[name] = "falta" if st == self.ana else "presente"
        self.client.post(url, data)
        self.assertTrue(self.fam_notes().filter(kind="frequencia", title__startswith="Falta registrada").exists())
        self.assertFalse(self.fam_notes(self.outra).exists())
        for st, name in form.rows:
            data[name] = "presente"
        self.client.post(url, data)
        self.assertTrue(self.fam_notes().filter(title__startswith="Falta corrigida").exists())

    def test_activity_correction_and_delivery(self):
        act = Activity.objects.create(school=self.school, class_group=self.cg, subject=self.mat, title="Tabuada",
                                      created_by=self.prof, status="publicada",
                                      published_date=timezone.localdate() - timedelta(days=1))
        self.login(self.prof)
        self.client.post(reverse("pedagogy:activity_submissions", args=[act.pk]),
                         {f"status_{self.ana.pk}": "entregue", f"nota_{self.ana.pk}": "9"})
        kinds = set(self.fam_notes().filter(kind="atividade").values_list("title", flat=True))
        self.assertIn("Atividade corrigida: Tabuada", kinds)
        self.assertTrue(any(t.startswith("Tabuada:") for t in kinds))
        # Reenviar o mesmo não duplica.
        before = self.fam_notes().count()
        self.client.post(reverse("pedagogy:activity_submissions", args=[act.pk]),
                         {f"status_{self.ana.pk}": "entregue", f"nota_{self.ana.pk}": "9"})
        self.assertEqual(self.fam_notes().count(), before)

    def test_internal_observation_is_never_shared(self):
        self.login(self.prof)
        base = {"student": self.ana.pk, "content": "Leitura", "observed_at": timezone.localdate().isoformat()}
        self.client.post(reverse("pedagogy:observation_create"), dict(base, dificuldades="Fluência interna"))
        self.client.post(reverse("pedagogy:observation_create"),
                         dict(base, dificuldades="Pode ler em casa", shared_with_family="on"))
        self.assertEqual(self.fam_notes().filter(kind="observacao").count(), 1)
        self.login(self.fam)
        page = self.client.get(reverse("pedagogy:observation_list") + f"?estudante={self.ana.pk}")
        shown = [o.dificuldades for o in page.context["observations"]]
        self.assertEqual(shown, ["Pode ler em casa"])


class RulesAndPreferencesTests(FamBase):
    def test_direction_turns_event_off(self):
        self.login(self.prof)
        self.assertEqual(self.client.get(reverse("communication:notification_rules")).status_code, 403)
        self.login(self.dir)
        on = ["nota_publicada", "atividade_atribuida"]  # falta desligada
        self.client.post(reverse("communication:notification_rules"), {"ativo": on})
        self.assertFalse(NotificationRule.objects.get(school=self.school, event="falta_registrada").enabled)
        self.login(self.prof)
        today = timezone.localdate().isoformat()
        url = reverse("pedagogy:attendance_register", args=[self.cg.pk]) + f"?data={today}"
        form = self.client.get(url).context["form"]
        data = {"date": today, **{name: "falta" for _st, name in form.rows}}
        self.client.post(url, data)
        self.assertFalse(self.fam_notes().filter(kind="frequencia").exists())
        self.assertTrue(AttendanceRecord.objects.filter(status="falta").exists())

    def test_person_mutes_kind_but_not_occurrence(self):
        self.login(self.fam)
        self.client.post(reverse("communication:notification_preferences"), {"receber": ["avaliacao"]})
        self.assertTrue(NotificationMute.objects.filter(user=self.fam, kind="frequencia").exists())
        from apps.communication.family_events import notify_family

        notify_family(self.ana, "falta_registrada", "Falta")
        notify_family(self.ana, "ocorrencia", "Ocorrência")
        kinds = set(self.fam_notes().values_list("kind", flat=True))
        self.assertEqual(kinds, {"ocorrencia"})

    def test_center_filters_by_student_and_date(self):
        from apps.communication.family_events import notify_family

        GuardianLink.objects.create(school=self.school, guardian=self.fam, student=self.bia, status="aprovado")
        notify_family(self.ana, "falta_registrada", "Falta da Ana")
        notify_family(self.bia, "falta_registrada", "Falta da Bia", dedupe_key="b")
        self.login(self.fam)
        page = self.client.get(reverse("communication:notification_list") + f"?aluno={self.ana.pk}")
        self.assertContains(page, "Falta da Ana")
        self.assertNotContains(page, "Falta da Bia")
        future = (timezone.localdate() + timedelta(days=1)).isoformat()
        self.assertNotContains(self.client.get(reverse("communication:notification_list") + f"?de={future}"),
                               "Falta da Ana")


class EmailChannelTests(FamBase):
    def test_off_by_default(self):
        from apps.communication.family_events import notify_family

        GuardianProfile.objects.create(user=self.fam, comm_preference="email")
        notify_family(self.ana, "falta_registrada", "Falta")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(NOTIFY_BY_EMAIL=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_generic_email_without_student_data(self):
        from apps.communication.family_events import notify_family

        GuardianProfile.objects.create(user=self.fam, comm_preference="email")
        GuardianProfile.objects.create(user=self.outra, comm_preference="nenhum")
        notify_family(self.ana, "falta_registrada", "Falta registrada em 10/03", body="Ana teve falta")
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["fam@x.com"])
        self.assertNotIn("Ana", msg.body + msg.subject)


class DeadlineReminderTests(FamBase):
    """Lembrete de prazo (véspera ou dia) sem agendador."""

    def make(self, deadline, **kw):
        today = timezone.localdate()
        return Activity.objects.create(school=self.school, class_group=self.cg, subject=self.mat, title="Mapa",
                                       deadline=deadline, published_date=kw.pop("published", today - timedelta(days=3)),
                                       class_date=today, created_by=self.prof, notified_at=timezone.now(), **kw)

    def reminders(self, user=None):
        return self.fam_notes(user).filter(dedupe_key__startswith="prazo:")

    def test_reminds_only_who_has_not_delivered_once(self):
        from apps.communication.family_events import send_deadline_reminders
        from apps.pedagogy.models import Submission

        today = timezone.localdate()
        act = self.make(today + timedelta(days=1))
        Submission.objects.create(school=self.school, activity=act, student=self.bia, status="entregue")
        send_deadline_reminders(today)
        n = self.reminders().get()
        self.assertEqual((n.title, n.student, n.kind), ("Prazo amanhã: Mapa", self.ana, "atividade"))
        self.assertFalse(self.reminders(self.outra).exists())  # Bia já entregou
        # No dia do prazo não repete o lembrete.
        send_deadline_reminders(today + timedelta(days=1))
        self.assertEqual(self.reminders().count(), 1)

    def test_ignores_far_deadlines_drafts_canceled_and_scheduled(self):
        from apps.communication.family_events import send_deadline_reminders

        today = timezone.localdate()
        self.make(today + timedelta(days=3))
        self.make(today, status="rascunho")
        self.make(today, status="cancelada", visible_before_cancel=True)
        self.make(today + timedelta(days=1), published=today + timedelta(days=1))  # ainda agendada
        self.make(today - timedelta(days=1))  # prazo vencido
        send_deadline_reminders(today)
        self.assertFalse(self.reminders().exists())

    def test_rule_off_and_personal_mute(self):
        from apps.communication.family_events import send_deadline_reminders

        today = timezone.localdate()
        self.make(today)
        NotificationMute.objects.create(user=self.outra, kind="atividade")
        send_deadline_reminders(today)
        self.assertEqual(self.reminders().get().title, "Prazo hoje: Mapa")
        self.assertFalse(self.reminders(self.outra).exists())
        Notification.objects.all().delete()
        NotificationRule.objects.create(school=self.school, event="prazo_proximo", enabled=False)
        send_deadline_reminders(today)
        self.assertFalse(Notification.objects.filter(dedupe_key__startswith="prazo:").exists())

    def test_runs_from_the_first_request_of_the_day(self):
        from apps.core.middleware import ScheduledPublicationMiddleware as M

        self.make(timezone.localdate())
        M._last_run = M._last_day = M._last_reminder_day = None
        self.login(self.prof)
        self.client.get(reverse("home"))
        self.assertTrue(self.reminders().exists())
        Notification.objects.all().delete()
        self.client.get(reverse("home"))  # mesmo dia: não roda de novo
        self.assertFalse(self.reminders().exists())
