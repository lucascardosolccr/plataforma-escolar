"""Histórico escolar consolidado (Prompt 14 §9.1; Prompt 13 §6.4)."""

import datetime as dt
from decimal import Decimal

from django.urls import reverse

from apps.academics.models import ClassGroup, SchoolYear
from apps.communication.tests.test_communication import CommunicationBase
from apps.core.models import AuditLog
from apps.pedagogy.models import AttendanceRecord, Evaluation, Grade
from apps.registry.models import Enrollment


class SchoolRecordTests(CommunicationBase):
    def setUp(self):
        super().setUp()
        # Ano anterior: Ana estava no "Pré" e saiu com matrícula concluída.
        self.year0 = SchoolYear.objects.create(school=self.school, name="2025", start_date=dt.date(2025, 2, 1))
        self.year.start_date = dt.date(2026, 2, 1)
        self.year.save()
        self.pre = ClassGroup.objects.create(school=self.school, school_year=self.year0, name="Pré B", grade="Pré")
        Enrollment.objects.create(school=self.school, student=self.ana, class_group=self.pre, school_year=self.year0,
                                  status="concluido")
        self.url = reverse("school_record", args=[self.ana.pk])

    def _grade(self, class_group, value, status="publicada", date=dt.date(2026, 3, 10)):
        ev = Evaluation.objects.create(school=self.school, subject=self.mat, class_group=class_group,
                                       title=f"P {value}", status=status, date=date, created_by=self.prof)
        Grade.objects.create(school=self.school, evaluation=ev, student=self.ana, value=Decimal(value))

    def test_averages_and_attendance_are_kept_per_year_and_class(self):
        self._grade(self.pre, "4.0", date=dt.date(2025, 5, 2))
        self._grade(self.turma, "8.0")
        self._grade(self.turma, "6.0")
        self._grade(self.turma, "1.0", status="rascunho")  # não publicada: fica fora
        for day, st in ((1, "presente"), (2, "presente"), (3, "falta"), (4, "presente")):
            AttendanceRecord.objects.create(school=self.school, class_group=self.turma, student=self.ana,
                                            date=dt.date(2026, 3, day), status=st)
        self.login("sec")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        years = resp.context["years"]
        self.assertEqual([y["enrollment"].school_year.name for y in years], ["2025", "2026"])
        self.assertEqual(float(years[0]["subjects"][0]["average"]), 4.0)
        self.assertTrue(years[0]["subjects"][0]["below"])
        self.assertEqual(float(years[1]["subjects"][0]["average"]), 7.0)
        self.assertEqual(years[1]["subjects"][0]["count"], 2)
        self.assertEqual(years[1]["attendance"]["percent"], 75.0)
        self.assertEqual(years[0]["attendance"]["total"], 0)
        self.assertContains(resp, "sem chamada registrada nesta turma")
        self.assertContains(resp, "Não substitui o histórico escolar oficial")
        self.assertTrue(AuditLog.objects.filter(user=self.sec, action="view",
                                                detail__contains="histórico escolar").exists())

    def test_school_record_access(self):
        self.login("resp")  # responsável com vínculo aprovado
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertContains(self.client.get(reverse("student_detail", args=[self.ana.pk])), self.url)
        self.login("prof")  # professor acompanha pelo painel restrito às próprias disciplinas
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertNotContains(self.client.get(reverse("student_detail", args=[self.ana.pk])), self.url)
        self.login("resp_b")  # outra escola
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.login("dir")
        self.assertEqual(self.client.get(reverse("school_record", args=[self.bea.pk])).status_code, 200)
