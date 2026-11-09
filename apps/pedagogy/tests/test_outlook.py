"""Agenda e faltas: faltas que ainda cabem no ano (calendário oficial × limite), onde as faltas pesam (quadro de
horários) e a agenda única de atividades, trabalhos e provas."""

import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse

from apps.academics.models import Subject
from apps.communication.models import Notification
from apps.communication.tests.test_communication import CommunicationBase
from apps.pedagogy import outlook
from apps.pedagogy.models import Activity, AttendanceRecord, Evaluation, SchoolConfig, Submission
from apps.pedagogy.views import _flag_attendance_limits
from apps.registry.models import Student
from apps.rotina.models import ClassSchedule
from apps.school_calendar.models import CalendarPublication

MON = dt.date(2026, 3, 2)  # segunda-feira
TODAY = dt.date(2026, 3, 20)  # sexta da 3ª semana


class MaxAbsencesTests(SimpleTestCase):
    def test_exact_fraction(self):
        self.assertEqual(outlook.max_absences(200, Decimal("25")), 50)
        self.assertEqual(outlook.max_absences(203, Decimal("25")), 50)   # 50,75 → 50
        self.assertEqual(outlook.max_absences(200, Decimal("20")), 40)
        self.assertEqual(outlook.max_absences(30, Decimal("10")), 3)     # 3,0 exato (não 2,999…)

    def test_levels(self):
        self.assertEqual(outlook.level_for(0, 50)[0], "ok")
        self.assertEqual(outlook.level_for(25, 50)[0], "atencao")
        self.assertEqual(outlook.level_for(38, 50)[0], "alerta")
        self.assertEqual(outlook.level_for(50, 50)[0], "alerta")
        self.assertEqual(outlook.level_for(51, 50)[0], "acima")


class OutlookBase(CommunicationBase):
    def setUp(self):
        super().setUp()
        # Ano letivo curto: 4 semanas de segunda a sexta = 20 dias letivos; limite de 25% → no máximo 5 faltas.
        self.year.start_date, self.year.end_date, self.year.is_current = MON, MON + dt.timedelta(days=25), True
        self.year.save()
        CalendarPublication.objects.create(school_year=self.year, published_by=self.direc)
        self.por = Subject.objects.create(school=self.school, name="Português")
        for wd, subj, n in ((0, self.mat, 2), (0, self.por, 1), (1, self.mat, 1), (2, self.por, 2)):
            for k in range(n):
                ClassSchedule.objects.create(school=self.school, class_group=self.turma, weekday=wd, subject=subj,
                                             start_time=dt.time(7 + k), end_time=dt.time(8 + k))

    def mark(self, day, status="falta", student=None):
        AttendanceRecord.objects.create(school=self.school, class_group=self.turma, student=student or self.ana,
                                        date=day, status=status, recorded_by=self.prof)


class AttendanceOutlookTests(OutlookBase):
    def test_left_absences_follow_the_official_calendar_and_the_school_limit(self):
        self.mark(MON)                          # segunda: 2 aulas de Matemática + 1 de Português
        self.mark(MON + dt.timedelta(days=1))   # terça: 1 de Matemática
        self.mark(MON + dt.timedelta(days=2), "atraso")  # atraso conta como presença
        o = outlook.attendance_outlook(self.ana, TODAY)
        self.assertEqual((o["total_days"], o["estimated"], o["allowed"], o["absences"], o["left"]), (20, False, 5, 2, 3))
        self.assertEqual(o["remaining_days"], 5)
        self.assertEqual(o["level"], "ok")
        rows = {r["subject"]: r for r in o["subjects"]}
        self.assertEqual(rows["Matemática"]["missed"], 3)
        self.assertEqual(rows["Português"]["missed"], 1)
        # 3 segundas e 3 terças até hoje: Matemática teve 3×2 + 3×1 = 9 aulas; no ano, 4×3 = 12
        self.assertEqual((rows["Matemática"]["given"], rows["Matemática"]["year_total"]), (9, 12))
        self.assertEqual(o["subjects"][0]["subject"], "Matemática")  # onde mais pesa vem primeiro

    def test_school_limit_and_levels(self):
        SchoolConfig.objects.create(school=self.school, max_absences_percent=Decimal("20"))
        for i in range(4):
            self.mark(MON + dt.timedelta(days=i))
        o = outlook.attendance_outlook(self.ana, TODAY)
        self.assertEqual((o["allowed"], o["left"], o["level"]), (4, 0, "alerta"))
        self.mark(MON + dt.timedelta(days=7))
        o = outlook.attendance_outlook(self.ana, TODAY)
        self.assertEqual((o["left"], o["over"], o["level"]), (-1, 1, "acima"))

    def test_without_published_calendar_estimates_200_days_and_without_schedule_says_so(self):
        CalendarPublication.objects.all().delete()
        ClassSchedule.objects.all().delete()
        o = outlook.attendance_outlook(self.ana, TODAY)
        self.assertEqual((o["total_days"], o["estimated"], o["allowed"], o["remaining_days"]), (200, True, 50, None))
        self.assertIsNone(o["subjects"])


class AgendaTests(OutlookBase):
    def activity(self, deadline, **kw):
        return Activity.objects.create(school=self.school, class_group=self.turma, subject=self.mat,
                                       title=kw.pop("title", f"Tarefa {deadline}"), created_by=self.prof,
                                       status=kw.pop("status", Activity.Status.PUBLISHED),
                                       published_date=kw.pop("published", TODAY - dt.timedelta(days=10)),
                                       deadline=deadline, **kw)

    def test_one_timeline_with_activities_and_exams_in_date_order(self):
        soon = self.activity(TODAY + dt.timedelta(days=1), title="Lista amanhã")
        self.activity(TODAY + dt.timedelta(days=4), title="Rascunho", status=Activity.Status.DRAFT)
        Activity.objects.create(school=self.school, class_group=self.turma_b, subject=self.mat, title="Outra turma",
                                created_by=self.prof, status=Activity.Status.PUBLISHED,
                                published_date=TODAY - dt.timedelta(days=3), deadline=TODAY + dt.timedelta(days=2))
        late = self.activity(TODAY - dt.timedelta(days=3), title="Venceu sem entrega")
        done = self.activity(TODAY - dt.timedelta(days=2), title="Venceu e entregou")
        Submission.objects.create(school=self.school, activity=done, student=self.ana, status="entregue")
        Evaluation.objects.create(school=self.school, subject=self.por, class_group=self.turma, title="Prova bimestral",
                                  date=TODAY + dt.timedelta(days=5), announced=True, created_by=self.prof)
        Evaluation.objects.create(school=self.school, subject=self.por, class_group=self.turma, title="Prova secreta",
                                  date=TODAY + dt.timedelta(days=6), created_by=self.prof)
        items = outlook.upcoming(self.ana, TODAY)
        self.assertEqual([i["title"] for i in items], ["Venceu sem entrega", "Lista amanhã", "Prova bimestral"])
        self.assertEqual([i["kind"] for i in items], ["atividade", "atividade", "prova"])
        self.assertEqual((items[0]["tone"], items[0]["note"]), ("late", "venceu sem entrega registrada"))
        self.assertEqual((items[1]["when"], items[1]["tone"]), ("amanhã", "urgent"))
        self.assertEqual(items[1]["url"], reverse("pedagogy:activity_detail", args=[soon.pk]))
        self.assertTrue(late.pk)


class PagesAndAlertsTests(OutlookBase):
    def test_family_and_student_see_it_staff_with_access_too_others_do_not(self):
        url = reverse("pedagogy:outlook")
        self.client.force_login(self.resp)
        with mock.patch("apps.pedagogy.outlook.timezone.localdate", return_value=TODAY):
            page = self.client.get(url)
        self.assertContains(page, "Agenda e faltas de Ana")
        self.assertContains(page, "faltas ainda cabem no ano")
        self.assertEqual(self.client.get(f"{url}?estudante={self.bea.pk}").status_code, 403)
        self.client.force_login(self.direc)
        self.assertEqual(self.client.get(f"{url}?estudante={self.ana.pk}").status_code, 200)
        self.client.force_login(self.resp_b)
        self.assertEqual(self.client.get(f"{url}?estudante={self.ana.pk}").status_code, 403)
        outsider = Student.objects.create(school=self.school_b, first_name="Zé")
        self.client.force_login(self.direc)
        self.assertEqual(self.client.get(f"{url}?estudante={outsider.pk}").status_code, 403)

    def test_home_shows_the_agenda_and_the_absences_left(self):
        self.client.force_login(self.resp)
        home = self.client.get(reverse("home"))
        self.assertContains(home, "Próximas entregas e provas")
        self.assertContains(home, "no ano")

    def test_attendance_page_points_family_to_the_yearly_count_and_dashboard_too(self):
        self.client.force_login(self.resp)
        self.assertContains(self.client.get(reverse("pedagogy:attendance_list")), reverse("pedagogy:outlook"))
        self.client.force_login(self.direc)
        dash = self.client.get(reverse("analytics:student_dashboard", args=[self.ana.pk]))
        self.assertContains(dash, f'{reverse("pedagogy:outlook")}?estudante={self.ana.pk}')

    def test_team_is_reminded_of_what_the_family_view_depends_on(self):
        self.client.force_login(self.direc)
        page = self.client.get(reverse("pending_center"))
        self.assertContains(page, "Turmas sem quadro de horários")  # 1º Ano B tem estudante e não tem quadro
        self.assertNotContains(page, "Publicar o calendário oficial")
        CalendarPublication.objects.all().delete()
        self.assertContains(self.client.get(reverse("pending_center")), "Publicar o calendário oficial de 2026")
        self.client.force_login(self.resp)
        self.assertNotContains(self.client.get(reverse("pending_center")), "quadro de horários")

    def test_alert_only_near_the_yearly_limit_and_once_per_level(self):
        for i in range(3):  # 3 de 5 permitidas: 60%, sem aviso (antes, 3 faltas em 3 dias = 100% avisava)
            self.mark(MON + dt.timedelta(days=i))
            _flag_attendance_limits(self.turma, MON + dt.timedelta(days=i))
        self.assertFalse(Notification.objects.filter(title__contains="Faltas").exists())
        self.mark(MON + dt.timedelta(days=3))  # 4 de 5: 80% → perto do limite
        for _ in range(2):
            _flag_attendance_limits(self.turma, MON + dt.timedelta(days=3))
        family = Notification.objects.filter(user=self.resp, title__contains="perto do limite do ano")
        self.assertEqual(family.count(), 1)
        self.assertIn("ainda cabem 1", family.get().body)
        self.assertTrue(Notification.objects.filter(user=self.sec, title__startswith="Faltas perto do limite").exists())
        for i in (4, 7):  # 6 faltas: acima do máximo
            self.mark(MON + dt.timedelta(days=i))
        _flag_attendance_limits(self.turma, MON + dt.timedelta(days=7))
        self.assertEqual(Notification.objects.filter(user=self.resp, title__contains="acima do máximo").count(), 1)
