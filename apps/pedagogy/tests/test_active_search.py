"""Busca ativa: relação para o Conselho Tutelar (LDB art. 12, VIII) e ações da escola (ECA art. 56, II)."""

from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear
from apps.coordination.models import CoordinatorAssignment
from apps.core.models import AuditLog, Role, School, User
from apps.pedagogy import active_search as svc
from apps.pedagogy.models import AbsenceJustification, ActiveSearchAction, AttendanceRecord
from apps.registry.models import Enrollment, Student


def weekdays_back(n, until):
    out, d = [], until - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


class ActiveSearchTests(TestCase):
    coordenacao_restrita = True  # conftest: sem a designação automática "escola toda"

    def setUp(self):
        self.today = timezone.localdate()
        self.school = School.objects.create(name="Escola", code="e")
        pw = "Senha-forte-123"
        mk = lambda u, r: User.objects.create_user(u, password=pw, role=r, school=self.school)  # noqa: E731
        self.direc, self.sec, self.coord = mk("dir", Role.DIRECAO), mk("sec", Role.SECRETARIA), mk("coord", Role.COORDENACAO)
        self.prof, self.fam, self.admin = mk("prof", Role.PROFESSOR), mk("fam", Role.RESPONSAVEL), mk("adm", Role.ADMIN)
        # ano sem início e fim cadastrados: vale o mínimo da LDB (200 dias), limite de 15 faltas
        self.year = SchoolYear.objects.create(school=self.school, name=str(self.today.year), is_current=True)
        self.a = ClassGroup.objects.create(school=self.school, school_year=self.year, name="6º A")
        self.b = ClassGroup.objects.create(school=self.school, school_year=self.year, name="6º B")
        self.students = {}
        for name, cg in (("Ana", self.a), ("Bia", self.a), ("Caio", self.a), ("Dani", self.b)):
            st = Student.objects.create(school=self.school, first_name=name, last_name="Teste")
            Enrollment.objects.create(school=self.school, student=st, class_group=cg, school_year=self.year)
            self.students[name] = st
        days = weekdays_back(40, self.today)
        self.days = days
        plan = {"Ana": set(days[:16]), "Bia": set(days[:15]), "Caio": set(days[-3:]), "Dani": set(days[:2])}
        for name, st in self.students.items():
            cg = self.a if name != "Dani" else self.b
            AttendanceRecord.objects.bulk_create([
                AttendanceRecord(school=self.school, class_group=cg, student=st, date=d,
                                 status="falta" if d in plan[name] else "presente") for d in days])
        AbsenceJustification.objects.create(school=self.school, student=self.students["Ana"], class_group=self.a,
                                            start_date=days[0], end_date=days[4], reason="Doença",
                                            status=AbsenceJustification.Status.APPROVED)

    def test_rule_and_lists(self):
        self.assertEqual(svc.limit_for(200), 15)
        data = svc.overview(self.direc, self.today)
        self.assertEqual(data["limit"], 15)
        self.assertIn("mínimo da LDB", data["source"])
        self.assertEqual([r["student"].first_name for r in data["notify"]], ["Ana"])  # 16 > 15
        ana = data["notify"][0]
        self.assertEqual((ana["absences"], ana["unjustified"]), (16, 11))  # 5 dias justificados
        att = {r["student"].first_name: r for r in data["attention"]}
        self.assertTrue(att["Bia"]["at_limit"])  # exatamente 15: ainda não "acima de"
        self.assertEqual(att["Caio"]["streak"], 3)
        self.assertNotIn("Dani", att)

    def test_calendar_days_change_the_limit(self):
        self.year.start_date, self.year.end_date = date(self.today.year, 2, 1), date(self.today.year, 12, 15)
        self.year.save()
        n, source, _ = svc.school_days_in_year(self.school)
        self.assertIn("calendário", source + "dias úteis")
        self.assertAlmostEqual(svc.limit_for(n), n * 0.25 * 0.30)

    def test_access_and_scope(self):
        url = reverse("pedagogy:active_search")
        student_url = reverse("pedagogy:active_search_student", args=[self.students["Ana"].pk])
        for user in (self.direc, self.sec):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 200)
            self.assertEqual(self.client.get(student_url).status_code, 200)
        for user in (self.prof, self.fam, self.admin):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403, user.username)
            self.assertEqual(self.client.get(student_url).status_code, 403, user.username)
        # coordenação que acompanha só o 6º B não vê a Ana
        d = CoordinatorAssignment.objects.create(school=self.school, coordinator=self.coord,
                                                 starts_on=self.today - timedelta(days=30))
        d.class_groups.set([self.b])
        self.client.force_login(self.coord)
        r = self.client.get(url)
        self.assertEqual(r.context["data"]["notify"], [])
        self.assertEqual(self.client.get(student_url).status_code, 403)
        self.assertEqual(svc.notify_count(self.coord), 0)
        self.assertTrue(AuditLog.objects.filter(detail__startswith="Consultou a busca ativa").exists())

    def test_actions_notification_and_pending(self):
        self.client.force_login(self.direc)
        self.assertEqual(svc.notify_count(self.direc), 1)
        self.assertContains(self.client.get(reverse("pending_center")),
                            "Estudantes acima do limite de faltas sem notificação ao Conselho Tutelar")
        url = reverse("pedagogy:active_search_student", args=[self.students["Ana"].pk])
        r = self.client.post(url, {"date": (self.today + timedelta(days=1)).isoformat(), "kind": "telefone",
                                   "outcome": "x"})
        self.assertIn("date", r.context["form"].errors)  # ação se registra depois de feita
        self.client.post(url, {"date": self.today.isoformat(), "kind": "telefone",
                               "outcome": "Mãe atendeu; combinamos retorno na segunda."})
        self.assertEqual(svc.overview(self.direc)["notify"][0]["school_actions"], 1)
        self.client.post(url, {"date": self.today.isoformat(), "kind": "conselho", "outcome": "Ofício 12/2026."})
        data = svc.overview(self.direc)
        self.assertEqual(([r["student"].first_name for r in data["notify"]],
                          [r["student"].first_name for r in data["notified"]]), ([], ["Ana"]))
        self.assertEqual(svc.notify_count(self.direc), 0)
        self.assertEqual(ActiveSearchAction.objects.filter(student=self.students["Ana"]).count(), 2)
        self.assertTrue(AuditLog.objects.filter(detail__startswith="Registrou na busca ativa").exists())
        page = self.client.get(url)
        self.assertContains(page, "Ofício 12/2026.")
        self.assertContains(page, "justificada")
