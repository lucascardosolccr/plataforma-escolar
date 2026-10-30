"""Calendário oficial, dias letivos, cardápio e quadro de horários (Prompt 14, rodada 5)."""

from datetime import date, time, timedelta

from django.test import TestCase
from django.urls import reverse

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.communication.models import Notification
from apps.core.models import Role, School, User
from apps.registry.models import Enrollment, GuardianLink, Student
from apps.rotina.models import ClassSchedule, MealMenu
from apps.school_calendar.models import CalendarEvent, CalendarPeriod, CalendarPublication
from apps.school_calendar.services import countdown, school_days

PW = "Senha-forte-123"


class Base(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        # 2026-03-02 é segunda-feira.
        self.year = SchoolYear.objects.create(school=self.school, name="2026", is_current=True,
                                              start_date=date(2026, 3, 2), end_date=date(2026, 3, 31))
        self.cg = ClassGroup.objects.create(school=self.school, school_year=self.year, name="3º A")
        self.other_cg = ClassGroup.objects.create(school=self.school, school_year=self.year, name="3º B")
        self.mat = Subject.objects.create(school=self.school, name="Matemática")
        self.users = {r: User.objects.create_user(r, password=PW, role=r, school=self.school) for r in Role.values}
        self.prof = self.users[Role.PROFESSOR]
        TeacherAssignment.objects.create(school=self.school, school_year=self.year, teacher=self.prof,
                                         class_group=self.cg, subject=self.mat)
        self.ana = Student.objects.create(school=self.school, first_name="Ana", user=self.users[Role.ESTUDANTE])
        Enrollment.objects.create(school=self.school, student=self.ana, class_group=self.cg, school_year=self.year)
        GuardianLink.objects.create(school=self.school, guardian=self.users[Role.RESPONSAVEL], student=self.ana,
                                    status="aprovado")

    def login(self, role):
        self.client.logout()
        self.client.login(username=role, password=PW)


class SchoolDaysTests(Base):
    def test_weekends_holidays_recess_and_extra_days(self):
        # Março/2026 a partir do dia 2: 22 dias úteis.
        self.assertEqual(len(school_days(self.year, self.year.start_date, self.year.end_date)), 22)
        CalendarEvent.objects.create(school=self.school, school_year=self.year, kind="feriado", title="Feriado",
                                     start=date(2026, 3, 19), no_classes=True)
        CalendarEvent.objects.create(school=self.school, school_year=self.year, kind="recesso", title="Recesso",
                                     start=date(2026, 3, 23), end=date(2026, 3, 25), no_classes=True)
        CalendarEvent.objects.create(school=self.school, school_year=self.year, kind="letivo_extra",
                                     title="Sábado letivo", start=date(2026, 3, 14))
        # Reunião não tira aula: só eventos "sem aula" contam.
        CalendarEvent.objects.create(school=self.school, school_year=self.year, kind="reuniao", title="Reunião",
                                     start=date(2026, 3, 10))
        self.assertEqual(len(school_days(self.year, self.year.start_date, self.year.end_date)), 22 - 1 - 3 + 1)

    def test_no_dates_means_no_count(self):
        self.year.start_date = None
        self.year.save()
        self.assertIsNone(school_days(self.year, date(2026, 3, 2), date(2026, 3, 31)))
        self.assertIn("reason", countdown(self.school, date(2026, 3, 10)))

    def test_countdown_only_after_publication_and_recalculates(self):
        today = date(2026, 3, 16)  # segunda
        self.assertIn("não foi publicado", countdown(self.school, today)["reason"])
        CalendarPublication.objects.create(school_year=self.year)
        CalendarPeriod.objects.create(school=self.school, school_year=self.year, kind="bimestre",
                                      name="1º bimestre", start=date(2026, 3, 2), end=date(2026, 3, 20))
        c = countdown(self.school, today)
        self.assertEqual(c["year_left"], 12)  # 16..31 úteis
        self.assertEqual(c["periods"][0]["left"], 5)  # 16..20
        CalendarEvent.objects.create(school=self.school, school_year=self.year, kind="suspensao",
                                     title="Suspensão", start=date(2026, 3, 17), no_classes=True)
        self.assertEqual(countdown(self.school, today)["periods"][0]["left"], 4)

    def test_vacation_and_return_day(self):
        CalendarPublication.objects.create(school_year=self.year)
        CalendarEvent.objects.create(school=self.school, school_year=self.year, kind="recesso", title="Recesso",
                                     start=date(2026, 3, 23), end=date(2026, 3, 27), no_classes=True)
        v = countdown(self.school, date(2026, 3, 16))["vacation"]
        self.assertEqual((v["days_until"], v["return"]), (7, date(2026, 3, 30)))


class OfficialCalendarViewTests(Base):
    def test_manage_roles_and_staff_only_events(self):
        for role, code in ((Role.SECRETARIA, 200), (Role.DIRECAO, 200), (Role.ADMIN, 200),
                           (Role.PROFESSOR, 403), (Role.RESPONSAVEL, 403), (Role.COORDENACAO, 403)):
            self.login(role)
            self.assertEqual(self.client.get(reverse("school_calendar:official")).status_code, code, role)
        self.login(Role.SECRETARIA)
        self.client.post(reverse("school_calendar:official"), {
            "form": "event", "e-kind": "reuniao", "e-title": "Reunião interna", "e-start": "2026-03-10",
            "e-audience": "equipe"})
        self.client.post(reverse("school_calendar:official"), {
            "form": "event", "e-kind": "feriado", "e-title": "Feriado municipal", "e-start": "2026-03-19",
            "e-audience": "todos", "e-notify": "on"})
        feriado = CalendarEvent.objects.get(title="Feriado municipal")
        self.assertTrue(feriado.no_classes)  # feriado é sempre sem aula
        self.assertTrue(Notification.objects.filter(user=self.users[Role.RESPONSAVEL], kind="calendario").exists())
        self.login(Role.RESPONSAVEL)
        page = self.client.get(reverse("school_calendar:calendar_index") + "?ver=mes&mes=2026-03")
        self.assertContains(page, "Feriado municipal")
        self.assertNotContains(page, "Reunião interna")
        self.login(Role.PROFESSOR)
        self.assertContains(self.client.get(reverse("school_calendar:calendar_index") + "?ver=mes&mes=2026-03"),
                            "Reunião interna")

    def test_publish_requires_year_dates(self):
        self.year.end_date = None
        self.year.save()
        self.login(Role.DIRECAO)
        self.client.post(reverse("school_calendar:official_publish", args=[self.year.pk]))
        self.assertFalse(CalendarPublication.objects.exists())


class MenuTests(Base):
    def test_nutrition_hidden_without_validator(self):
        self.login(Role.SECRETARIA)
        resp = self.client.post(reverse("rotina:menu_edit"), {
            "data": "2026-03-16", "lanche_manha-description": "Pão com queijo",
            "lanche_manha-allergens": "lactose, glúten"})
        self.assertContains(resp, "quem validou")
        self.assertFalse(MealMenu.objects.exists())
        self.client.post(reverse("rotina:menu_edit"), {"data": "2026-03-16", "lanche_manha-description": "Pão com queijo"})
        m = MealMenu.objects.get()
        self.assertFalse(m.show_nutrition)
        self.login(Role.RESPONSAVEL)
        page = self.client.get(reverse("rotina:menu") + "?semana=2026-03-16")
        self.assertContains(page, "Pão com queijo")
        self.assertNotContains(page, "<summary>Ingredientes e alergênicos")

    def test_change_notifies_families_once(self):
        future = date.today() + timedelta(days=2)
        MealMenu.objects.create(school=self.school, date=future, meal="almoco", description="Arroz e feijão")
        self.login(Role.DIRECAO)
        self.client.post(reverse("rotina:menu_edit"), {
            "data": future.isoformat(), "almoco-description": "Macarrão", "almoco-changed": "on",
            "almoco-change_note": "Falta de gás", "notify": "1"})
        avisos = Notification.objects.filter(kind="cardapio")
        self.assertEqual(set(avisos.values_list("user__role", flat=True)), {Role.RESPONSAVEL, Role.ESTUDANTE})
        self.assertEqual(MealMenu.objects.get().description, "Macarrão")

    def test_only_managers_edit(self):
        for role in (Role.PROFESSOR, Role.RESPONSAVEL, Role.ESTUDANTE, Role.COORDENACAO):
            self.login(role)
            self.assertEqual(self.client.get(reverse("rotina:menu_edit")).status_code, 403, role)
            self.assertEqual(self.client.get(reverse("rotina:menu")).status_code, 200, role)


class ScheduleTests(Base):
    def add(self, cg=None, weekday=0, start=time(7, 30), end=time(8, 20)):
        return ClassSchedule.objects.create(school=self.school, class_group=cg or self.cg, weekday=weekday,
                                            start_time=start, end_time=end, subject=self.mat, teacher=self.prof)

    def test_conflicts_are_refused(self):
        self.add()
        self.login(Role.SECRETARIA)
        resp = self.client.post(reverse("rotina:schedule_class", args=[self.cg.pk]), {
            "weekday": 0, "start_time": "08:00", "end_time": "08:50", "subject": self.mat.pk})
        self.assertContains(resp, "Conflita")
        resp = self.client.post(reverse("rotina:schedule_class", args=[self.other_cg.pk]), {
            "weekday": 0, "start_time": "07:30", "end_time": "08:20", "subject": self.mat.pk, "teacher": self.prof.pk})
        self.assertContains(resp, "já dá aula")
        self.assertEqual(ClassSchedule.objects.count(), 1)

    def test_teacher_defaults_from_assignment(self):
        self.login(Role.COORDENACAO)
        self.client.post(reverse("rotina:schedule_class", args=[self.cg.pk]), {
            "weekday": 2, "start_time": "09:00", "end_time": "09:50", "subject": self.mat.pk})
        self.assertEqual(ClassSchedule.objects.get().teacher, self.prof)

    def test_visibility_by_link(self):
        self.add()
        self.login(Role.ESTUDANTE)
        self.assertContains(self.client.get(reverse("rotina:schedule_index")), "Matemática")
        self.assertEqual(self.client.get(reverse("rotina:schedule_class", args=[self.other_cg.pk])).status_code, 403)
        self.login(Role.RESPONSAVEL)
        self.assertEqual(self.client.get(reverse("rotina:schedule_class", args=[self.cg.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("rotina:schedule_class", args=[self.other_cg.pk])).status_code, 403)
        self.login(Role.PROFESSOR)
        self.assertContains(self.client.get(reverse("rotina:schedule_index")), "3º A")
        self.assertEqual(self.client.get(reverse("rotina:schedule_class", args=[self.other_cg.pk])).status_code, 403)

    def test_home_shows_today_schedule_and_menu(self):
        today = date.today()
        if today.weekday() > 5:
            self.skipTest("domingo: sem quadro")
        self.add(weekday=today.weekday())
        MealMenu.objects.create(school=self.school, date=today, meal="lanche_manha", description="Fruta da estação")
        for role in (Role.ESTUDANTE, Role.RESPONSAVEL, Role.PROFESSOR):
            self.login(role)
            page = self.client.get(reverse("home"))
            self.assertContains(page, "Hoje na escola")
            self.assertContains(page, "Fruta da estação")
            self.assertContains(page, "Matemática", msg_prefix=role)


class MenuNutritionShownTests(Base):
    def test_validated_allergens_are_shown(self):
        MealMenu.objects.create(school=self.school, date=date(2026, 3, 16), meal="lanche_manha",
                                description="Bolo", allergens="ovo, glúten", validated_by="Nutricionista Carla")
        self.login(Role.RESPONSAVEL)
        page = self.client.get(reverse("rotina:menu") + "?semana=2026-03-16")
        self.assertContains(page, "<summary>Ingredientes e alergênicos")
        self.assertContains(page, "Validado por Nutricionista Carla")
