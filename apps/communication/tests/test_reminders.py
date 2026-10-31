"""Lembretes acadêmicos com antecedência configurável, provas e central (Prompt 15)."""

from datetime import timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from apps.communication import reminders
from apps.communication.models import Notification, ReminderPolicy, ReminderRun
from apps.communication.tests.test_family_events import PW, FamBase
from apps.core.models import Role, User
from apps.pedagogy.models import Activity, Evaluation, Submission


class Base(FamBase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.aluna = User.objects.create_user("ana.aluna", password=PW, role=Role.ESTUDANTE, school=self.school)
        self.ana.user = self.aluna
        self.ana.save()

    def act(self, deadline, **kw):
        return Activity.objects.create(
            school=self.school, class_group=self.cg, subject=self.mat, title=kw.pop("title", "Mapa"),
            deadline=deadline, published_date=self.today - timedelta(days=10), class_date=self.today,
            created_by=self.prof, notified_at=timezone.now() - timedelta(days=10), status="publicada", **kw)

    def policy(self, **kw):
        p = ReminderPolicy.for_school(self.school)
        for k, v in kw.items():
            setattr(p, k, v)
        p.save()
        return p

    def notes(self, user=None, **kw):
        return Notification.objects.filter(user=user or self.fam, **kw)


class StageTests(Base):
    def test_stage_math(self):
        offs = [7, 3, 1, 0]
        self.assertEqual([reminders.stage_before(d, offs) for d in (9, 7, 5, 3, 2, 1, 0, -1)],
                         [None, 7, 7, 3, 3, 1, 0, None])
        self.assertEqual([reminders.stage_after(d, [1, 3]) for d in (0, 1, 2, 3, 9)], [None, 1, 1, 3, 3])

    def test_each_configured_stage_reminds_once_and_missed_days_collapse(self):
        self.policy(activity_days="7,3,1,0")
        act = self.act(self.today + timedelta(days=7))
        for offset in range(0, 8):  # roda todos os dias, duas vezes por dia
            day = self.today + timedelta(days=offset)
            reminders.activity_reminders(day)
            reminders.activity_reminders(day)
        titles = sorted(self.notes(dedupe_key__startswith=f"prazo:{act.pk}:").values_list("title", flat=True))
        self.assertEqual(titles, ["Prazo amanhã: Mapa", "Prazo em 3 dias: Mapa", "Prazo em 7 dias: Mapa",
                                  "Prazo hoje: Mapa"])
        # Servidor desligado entre a etapa 7 e o dia 2: sai só a etapa vigente (3).
        Notification.objects.all().delete()
        act2 = self.act(self.today + timedelta(days=2), title="Resumo")
        reminders.activity_reminders(self.today)
        self.assertEqual(self.notes(dedupe_key__startswith=f"prazo:{act2.pk}:").count(), 1)

    def test_priority_ref_and_due_date_and_student_account(self):
        act = self.act(self.today + timedelta(days=1))
        reminders.activity_reminders(self.today)
        for user in (self.fam, self.aluna):
            n = self.notes(user).get()
            self.assertEqual((n.priority, n.ref, n.due_on, n.student), ("importante", f"atividade:{act.pk}",
                                                                         act.deadline, self.ana))
        self.assertEqual(self.notes(self.aluna).get().state(self.today), ("futura", f"Para {act.deadline:%d/%m}"))

    def test_only_student_when_school_turns_guardians_off(self):
        self.policy(include_guardians=False)
        self.act(self.today)
        reminders.activity_reminders(self.today)
        self.assertTrue(self.notes(self.aluna).exists())
        self.assertFalse(self.notes(self.fam).exists())
        # Bia não tem acesso próprio: a responsável dela continua sendo avisada.
        self.assertTrue(self.notes(self.outra).exists())

    def test_overdue_while_pending_only(self):
        self.policy(overdue_days="1,3")
        act = self.act(self.today - timedelta(days=1))
        Submission.objects.create(school=self.school, activity=act, student=self.bia, status="entregue")
        reminders.activity_reminders(self.today)
        n = self.notes().get(dedupe_key__startswith="atraso:")
        self.assertEqual((n.title, n.priority), ("Atividade pendente: Mapa", "importante"))
        self.assertFalse(self.notes(self.outra).exists())  # Bia entregou
        reminders.activity_reminders(self.today + timedelta(days=1))  # 2 dias: ainda etapa 1
        self.assertEqual(self.notes(dedupe_key__startswith="atraso:").count(), 1)
        reminders.activity_reminders(self.today + timedelta(days=2))  # 3 dias: etapa 3
        self.assertEqual(self.notes(dedupe_key__startswith="atraso:").count(), 2)

    def test_no_reminder_the_same_day_the_activity_was_announced(self):
        act = Activity.objects.create(school=self.school, class_group=self.cg, subject=self.mat, title="Nova",
                                      deadline=self.today + timedelta(days=3), published_date=self.today,
                                      class_date=self.today, created_by=self.prof, status="publicada",
                                      notified_at=timezone.now())
        reminders.activity_reminders(self.today)
        self.assertFalse(self.notes(dedupe_key__startswith=f"prazo:{act.pk}:").exists())


class ChangesTests(Base):
    def edit_url(self, act):
        return reverse("pedagogy:activity_edit", args=[act.pk])

    def post_activity(self, act, deadline):
        self.login(self.prof)
        data = {"class_group": act.class_group_id, "subject": act.subject_id, "title": act.title,
                "class_date": act.class_date.isoformat(), "published_date": act.published_date.isoformat(),
                "deadline": deadline.isoformat(), "description": "Ler."}
        return self.client.post(self.edit_url(act), data)

    def test_deadline_change_resolves_old_reminders_and_notifies(self):
        act = self.act(self.today + timedelta(days=1))
        reminders.activity_reminders(self.today)
        new = self.today + timedelta(days=5)
        r = self.post_activity(act, new)
        self.assertEqual(r.status_code, 302)
        act.refresh_from_db()
        self.assertEqual(act.deadline, new)
        old = self.notes().get(dedupe_key__startswith="prazo:")
        self.assertEqual(old.resolution, f"Prazo alterado para {new:%d/%m/%Y}")
        change = self.notes().get(title="Prazo alterado: Mapa")
        self.assertIn(f"para {new:%d/%m/%Y}", change.body)
        self.assertEqual((change.priority, change.due_on, change.resolved_at), ("importante", new, None))
        # As etapas recomeçam para a nova data.
        reminders.activity_reminders(new - timedelta(days=1))
        self.assertTrue(self.notes(dedupe_key=f"prazo:{act.pk}:{self.ana.pk}:{new:%Y%m%d}:1").exists())

    def test_delivery_resolves_and_stops_reminders(self):
        act = self.act(self.today + timedelta(days=1))
        reminders.activity_reminders(self.today)
        self.login(self.prof)
        self.client.post(reverse("pedagogy:activity_submissions", args=[act.pk]),
                         {f"status_{self.ana.pk}": "entregue"})
        n = self.notes().get(dedupe_key__startswith="prazo:")
        self.assertEqual(n.resolution, "Entrega registrada")
        self.assertEqual(n.state(), ("resolvida", "Entrega registrada"))
        reminders.activity_reminders(self.today + timedelta(days=1))
        self.assertEqual(self.notes(dedupe_key__startswith="prazo:").count(), 1)
        # A outra família (Bia não entregou) segue com o lembrete aberto.
        self.assertTrue(self.notes(self.outra, resolved_at__isnull=True).exists())

    def test_cancel_resolves(self):
        act = self.act(self.today + timedelta(days=1))
        reminders.activity_reminders(self.today)
        self.login(self.prof)
        self.client.post(reverse("pedagogy:activity_cancel", args=[act.pk]), {"cancel_reason": "Feriado"})
        self.assertFalse(self.notes(resolved_at__isnull=True).exists())
        self.assertTrue(self.notes(title="Atividade cancelada: Mapa").exists())
        reminders.activity_reminders(self.today + timedelta(days=1))
        self.assertEqual(self.notes(dedupe_key__startswith="prazo:").count(), 1)


class ExamTests(Base):
    def data(self, **kw):
        base = {"class_group": self.cg.pk, "subject": self.mat.pk, "title": "Prova 1", "kind": "", "weight": "1",
                "date": (self.today + timedelta(days=7)).isoformat(), "announced": "on", "description": ""}
        base.update(kw)
        return base

    def test_announce_change_and_delete(self):
        self.login(self.prof)
        self.client.post(reverse("pedagogy:evaluation_create"), self.data())
        ev = Evaluation.objects.get()
        self.assertTrue(ev.announced)
        n = self.notes().get(kind="prova")
        self.assertEqual((n.title, n.ref), ("Prova marcada: Prova 1", f"avaliacao:{ev.pk}"))
        self.assertTrue(self.notes(self.aluna, kind="prova").exists())
        # Data alterada
        new = self.today + timedelta(days=9)
        self.client.post(reverse("pedagogy:evaluation_edit", args=[ev.pk]), self.data(date=new.isoformat()))
        self.assertEqual(self.notes(title="Data da prova alterada: Prova 1").count(), 1)
        self.assertEqual(self.notes(title="Prova marcada: Prova 1").get().resolution,
                         f"Data alterada para {new:%d/%m/%Y}")
        # Salvar de novo sem mudar a data: nada novo.
        self.client.post(reverse("pedagogy:evaluation_edit", args=[ev.pk]), self.data(date=new.isoformat()))
        self.assertEqual(self.notes(kind="prova").count(), 2)
        # Excluir
        self.client.post(reverse("pedagogy:evaluation_edit", args=[ev.pk]), {"_delete": "1"})
        self.assertTrue(self.notes(title="Prova desmarcada: Prova 1").exists())
        self.assertFalse(self.notes(kind="prova", resolved_at__isnull=True).exists())

    def test_not_announced_is_silent_and_hidden(self):
        self.login(self.prof)
        self.client.post(reverse("pedagogy:evaluation_create"), self.data(announced=""))
        self.assertFalse(Notification.objects.filter(kind="prova").exists())
        reminders.exam_reminders(self.today + timedelta(days=6))
        self.assertFalse(Notification.objects.filter(kind="prova").exists())
        self.login(self.fam)
        r = self.client.get(reverse("school_calendar:calendar_index") + "?type=evaluation")
        self.assertNotContains(r, "Prova 1")

    def test_announced_shows_in_agenda_and_reminders(self):
        ev = Evaluation.objects.create(school=self.school, subject=self.mat, class_group=self.cg, title="Prova 2",
                                       date=self.today + timedelta(days=1), announced=True, created_by=self.prof)
        reminders.exam_reminders(self.today)
        reminders.exam_reminders(self.today)
        n = self.notes().get(kind="prova")
        self.assertEqual((n.title, n.priority, n.due_on), ("Prova amanhã: Prova 2", "importante", ev.date))
        self.login(self.fam)
        r = self.client.get(reverse("school_calendar:calendar_index") + "?type=evaluation")
        self.assertContains(r, "Prova 2")
        r = self.client.get(reverse("pedagogy:evaluation_list"))
        self.assertContains(r, "Próximas provas")
        # Outra escola / família sem vínculo não vê a nota (rascunho) nem nada além da data.
        self.assertNotContains(r, "Média")


class DailyRunTests(Base):
    def test_run_is_recorded_and_retried_after_failure(self):
        from apps.core.middleware import ScheduledPublicationMiddleware as M

        self.act(self.today)
        M._last_run = M._last_day = M._last_reminder_day = None
        with mock.patch("apps.communication.reminders.exam_reminders", side_effect=RuntimeError("falhou")):
            self.login(self.prof)
            self.client.get(reverse("home"))
        run = ReminderRun.objects.get()
        self.assertEqual(run.status, "erro")
        self.assertIn("RuntimeError", run.detail)
        self.assertIsNone(M._last_reminder_day)  # o dia não ficou dado como feito
        M._last_run = None
        self.client.get(reverse("home"))
        self.assertEqual(ReminderRun.objects.filter(status="ok").count(), 1)
        # A tentativa com falha já tinha criado o lembrete da atividade; a nova não duplicou.
        self.assertEqual(self.notes(dedupe_key__startswith="prazo:").count(), 1)
        M._last_run = None
        self.client.get(reverse("home"))
        self.assertEqual(ReminderRun.objects.count(), 2)  # dia concluído: não roda de novo


class PolicyAndCenterTests(Base):
    def test_policy_form_validates_and_saves(self):
        self.login(self.dir)
        url = reverse("communication:notification_rules")
        r = self.client.post(url, {"activity_days": "7, x, 99", "overdue_days": "0", "exam_days": ""})
        self.assertEqual(r.status_code, 200)
        form = r.context["form"]
        self.assertIn("activity_days", form.errors)
        self.assertIn("overdue_days", form.errors)
        self.assertIn("exam_days", form.errors)
        self.client.post(url, {"activity_days": "1, 7,3,7", "overdue_days": "2", "exam_days": "0,5"})
        p = ReminderPolicy.objects.get(school=self.school)
        self.assertEqual((p.activity_days, p.overdue_days, p.exam_days, p.include_guardians),
                         ("7, 3, 1", "2", "5, 0", False))
        self.login(self.prof)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_center_filters_by_priority_and_commitment_state(self):
        act = self.act(self.today + timedelta(days=1))
        reminders.activity_reminders(self.today)
        Notification.objects.create(school=self.school, user=self.fam, title="Comunicado geral")
        old = self.act(self.today + timedelta(days=1), title="Antiga")
        reminders.activity_reminders(self.today)
        reminders.resolve(f"atividade:{old.pk}", "Entrega registrada")
        self.login(self.fam)
        url = reverse("communication:notification_list")
        r = self.client.get(url + "?prioridade=importante")
        self.assertEqual({n.title for n in r.context["page"]}, {"Prazo amanhã: Mapa", "Prazo amanhã: Antiga"})
        r = self.client.get(url + "?estado=resolvidas")
        self.assertEqual([n.title for n in r.context["page"]], ["Prazo amanhã: Antiga"])
        r = self.client.get(url + "?estado=a_vencer")
        self.assertEqual([n.title for n in r.context["page"]], ["Prazo amanhã: Mapa"])
        self.assertContains(r, "Importante")
        self.assertContains(r, f"Para {act.deadline:%d/%m}")
        # Estudante também tem central própria, só com os avisos dele.
        self.login(self.aluna)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all(n.user_id == self.aluna.pk for n in r.context["page"]))
