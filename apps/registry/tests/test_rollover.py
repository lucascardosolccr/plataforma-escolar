"""Rematrícula em lote para o ano seguinte."""

import datetime

from django.test import TestCase
from django.urls import reverse

from apps.academics.models import ClassGroup, SchoolYear
from apps.core.models import AuditLog, Role, School, User
from apps.registry.models import Enrollment, Student

PW = "Senha-forte-123"
URL = reverse("enrollment_rollover")


class RolloverTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        self.y1 = SchoolYear.objects.create(school=self.school, name="2025", is_current=True,
                                            start_date=datetime.date(2025, 2, 1),
                                            end_date=datetime.date(2025, 12, 15))
        self.y2 = SchoolYear.objects.create(school=self.school, name="2026")
        self.c5 = ClassGroup.objects.create(school=self.school, school_year=self.y1, name="5º A")
        self.c6 = ClassGroup.objects.create(school=self.school, school_year=self.y2, name="6º A")
        self.c5b = ClassGroup.objects.create(school=self.school, school_year=self.y2, name="5º A")
        self.students = []
        for i, nome in enumerate(["Ana", "Bia", "Caio"]):
            s = Student.objects.create(school=self.school, first_name=nome, last_name="Silva",
                                       birth_date=datetime.date(2015, 1, 1 + i))
            Enrollment.objects.create(school=self.school, student=s, class_group=self.c5,
                                      school_year=self.y1, enrollment_number=f"N{i}")
            self.students.append(s)
        self.sec = User.objects.create_user("sec", password=PW, role=Role.SECRETARIA, school=self.school)
        self.client.login(username="sec", password=PW)

    def ids(self, *students):
        return [str(Enrollment.objects.get(student=s, class_group=self.c5).pk) for s in students]

    def test_moves_selected_and_keeps_history(self):
        ana, bia, caio = self.students
        r = self.client.post(URL, {"origem": self.c5.pk, "destino": self.c6.pk, "ids": self.ids(ana, bia)})
        self.assertRedirects(r, f"{URL}?origem={self.c5.pk}")
        old = Enrollment.objects.get(student=ana, school_year=self.y1)
        self.assertEqual((old.status, old.ended_on), ("concluido", datetime.date(2025, 12, 15)))
        new = Enrollment.objects.get(student=ana, school_year=self.y2)
        self.assertEqual((new.class_group, new.status, new.enrollment_number), (self.c6, "ativo", "N0"))
        # Caio ficou desmarcado (retido): segue ativo em 2025 e pode ir para o 5º A de 2026.
        self.assertEqual(Enrollment.objects.get(student=caio).status, "ativo")
        self.assertEqual(AuditLog.objects.filter(action="create", detail__startswith="Rematriculou").count(), 2)
        r = self.client.post(URL, {"origem": self.c5.pk, "destino": self.c5b.pk, "ids": self.ids(caio)})
        self.assertEqual(Enrollment.objects.get(student=caio, status="ativo").class_group, self.c5b)

    def test_resubmitting_does_not_duplicate(self):
        ids = self.ids(self.students[0])
        self.client.post(URL, {"origem": self.c5.pk, "destino": self.c6.pk, "ids": ids})
        self.client.post(URL, {"origem": self.c5.pk, "destino": self.c6.pk, "ids": ids})
        self.assertEqual(Enrollment.objects.filter(student=self.students[0], school_year=self.y2).count(), 1)

    def test_skips_who_already_has_enrollment_in_target_year(self):
        ana = self.students[0]
        Enrollment.objects.create(school=self.school, student=ana, class_group=self.c5b, school_year=self.y2)
        r = self.client.post(URL, {"origem": self.c5.pk, "destino": self.c6.pk, "ids": self.ids(ana)}, follow=True)
        self.assertContains(r, "Sem alteração")
        self.assertEqual(Enrollment.objects.get(student=ana, school_year=self.y1).status, "ativo")

    def test_blocked_before_origin_year_ends(self):
        self.y1.end_date = datetime.date.today() + datetime.timedelta(days=10)
        self.y1.save()
        r = self.client.get(URL, {"origem": self.c5.pk})
        self.assertContains(r, "fica disponível depois dessa data")
        self.assertNotContains(r, "Rematricular selecionados")
        self.client.post(URL, {"origem": self.c5.pk, "destino": self.c6.pk, "ids": self.ids(*self.students)})
        self.assertFalse(Enrollment.objects.filter(school_year=self.y2).exists())

    def test_year_without_end_date_needs_confirmation(self):
        self.y1.end_date = None
        self.y1.save()
        ids = self.ids(self.students[0])
        r = self.client.post(URL, {"origem": self.c5.pk, "destino": self.c6.pk, "ids": ids})
        self.assertContains(r, "Confirme que as aulas")
        self.assertFalse(Enrollment.objects.filter(school_year=self.y2).exists())
        self.client.post(URL, {"origem": self.c5.pk, "destino": self.c6.pk, "ids": ids, "confirmo": "1"})
        old = Enrollment.objects.get(student=self.students[0], school_year=self.y1)
        self.assertEqual((old.status, old.ended_on), ("concluido", datetime.date.today()))

    def test_validation_destination_and_selection(self):
        # Destino no mesmo ano da origem não é aceito.
        r = self.client.post(URL, {"origem": self.c5.pk, "destino": self.c5.pk, "ids": self.ids(self.students[0])})
        self.assertContains(r, "Escolha a turma de destino")
        r = self.client.post(URL, {"origem": self.c5.pk, "destino": self.c6.pk})
        self.assertContains(r, "Marque pelo menos um estudante")
        self.assertFalse(Enrollment.objects.filter(school_year=self.y2).exists())

    def test_other_school_and_roles(self):
        other = School.objects.create(name="Outra", code="o")
        oy = SchoolYear.objects.create(school=other, name="2026")
        oc = ClassGroup.objects.create(school=other, school_year=oy, name="X")
        self.assertEqual(self.client.get(URL, {"origem": oc.pk}).status_code, 404)
        r = self.client.post(URL, {"origem": self.c5.pk, "destino": oc.pk, "ids": self.ids(self.students[0])})
        self.assertContains(r, "Escolha a turma de destino")
        for role in (Role.PROFESSOR, Role.COORDENACAO, Role.RESPONSAVEL):
            User.objects.create_user(f"u{role}", password=PW, role=role, school=self.school)
            self.client.login(username=f"u{role}", password=PW)
            self.assertEqual(self.client.get(URL).status_code, 403, role)
