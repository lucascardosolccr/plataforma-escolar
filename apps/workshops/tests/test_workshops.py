"""Oficinas: criação pelo alcance, publicação com aviso, vagas, lista de espera e chamada automática."""

import datetime as dt

from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification
from apps.communication.tests.test_communication import CommunicationBase
from apps.core.models import Role, User
from apps.registry.models import Enrollment, GuardianLink, Student

from ..models import Signup, Workshop


class WorkshopTests(CommunicationBase):
    def setUp(self):
        super().setUp()
        self.year.is_current = True
        self.year.save()
        self.caio = Student.objects.create(school=self.school, first_name="Caio")
        Enrollment.objects.create(school=self.school, student=self.caio, class_group=self.turma, school_year=self.year)
        self.resp2 = User.objects.create_user(username="resp2", password="senha-forte-1", role=Role.RESPONSAVEL,
                                              school=self.school)
        GuardianLink.objects.create(school=self.school, guardian=self.resp2, student=self.caio, status="aprovado")

    def create(self, user="prof", **extra):
        self.login(user)
        today = timezone.localdate()
        data = {"title": "Robótica", "description": "Montagem e programação de robôs.", "schedule": "Terças, 14h",
                "starts_on": (today + dt.timedelta(days=7)).isoformat(),
                "ends_on": (today + dt.timedelta(days=60)).isoformat(), "capacity": 1,
                "signup_until": (today + dt.timedelta(days=5)).isoformat(), "class_groups": [self.turma.pk], **extra}
        return self.client.post(reverse("workshops:create"), data)

    def published(self, **extra):
        self.create(**extra)
        w = Workshop.objects.get()
        self.client.post(reverse("workshops:publish", args=[w.pk]))
        return w

    def join(self, w, user="resp", student=None):
        self.login(user)
        return self.client.post(reverse("workshops:sign_up", args=[w.pk]), {"estudante": (student or self.ana).pk})

    def test_teacher_creates_for_own_classes_and_families_see_it_only_after_publishing(self):
        self.create(class_groups=[self.turma_b.pk])
        self.create(class_groups=[])  # professor precisa escolher as próprias turmas
        self.assertFalse(Workshop.objects.exists())
        self.create()
        w = Workshop.objects.get()
        self.login("resp")
        self.assertEqual(self.client.get(reverse("workshops:detail", args=[w.pk])).status_code, 404)
        self.login("prof")
        self.client.post(reverse("workshops:publish", args=[w.pk]))
        self.assertTrue(Notification.objects.filter(user=self.resp, title="Inscrições abertas: Robótica").exists())
        self.login("resp")
        self.assertContains(self.client.get(reverse("workshops:index")), "Robótica")

    def test_waiting_list_is_called_in_order_when_someone_leaves(self):
        w = self.published()
        self.join(w)
        self.join(w, user="resp2", student=self.caio)
        self.assertEqual(dict(Signup.objects.values_list("student__first_name", "status")),
                         {"Ana": "inscrito", "Caio": "espera"})
        self.assertContains(self.client.get(reverse("workshops:detail", args=[w.pk])), "1º da fila")
        self.join(w, user="resp2", student=self.caio)  # repetir não muda a posição
        self.assertEqual(Signup.objects.count(), 2)
        self.login("resp")
        self.client.get(reverse("workshops:index"))  # consome o recado da outra família guardado no cookie de teste
        page = self.client.get(reverse("workshops:detail", args=[w.pk]))
        self.assertNotContains(page, "Caio")  # a família não vê os outros inscritos
        ana = Signup.objects.get(student=self.ana)
        self.client.post(reverse("workshops:cancel", args=[ana.pk]))
        self.assertEqual(Signup.objects.get(student=self.caio).status, "inscrito")
        self.assertTrue(Notification.objects.filter(user=self.resp2, title__startswith="Vaga confirmada").exists())
        self.join(w)  # volta, mas agora para o fim da fila
        self.assertEqual(Signup.objects.get(student=self.ana).status, "espera")

    def test_more_seats_call_the_queue_and_fewer_than_taken_is_refused(self):
        w = self.published()
        self.join(w)
        self.join(w, user="resp2", student=self.caio)
        self.login("prof")
        base = {"title": w.title, "description": w.description, "schedule": w.schedule,
                "starts_on": w.starts_on.isoformat(), "ends_on": w.ends_on.isoformat(),
                "signup_until": w.signup_until.isoformat(), "class_groups": [self.turma.pk]}
        self.client.post(reverse("workshops:edit", args=[w.pk]), {**base, "capacity": 2})
        self.assertEqual(Signup.objects.filter(status="inscrito").count(), 2)
        self.client.post(reverse("workshops:edit", args=[w.pk]), {**base, "capacity": 1})
        w.refresh_from_db()
        self.assertEqual(w.capacity, 2)

    def test_access(self):
        w = self.published()
        self.join(w)
        url = reverse("workshops:detail", args=[w.pk])
        bea_parent = User.objects.create_user(username="resp_bea", password="senha-forte-1",
                                              role=Role.RESPONSAVEL, school=self.school)
        GuardianLink.objects.create(school=self.school, guardian=bea_parent, student=self.bea, status="aprovado")
        User.objects.create_user(username="prof2", password="senha-forte-1", role=Role.PROFESSOR, school=self.school)
        for user, code in (("resp_bea", 404), ("resp_b", 404), ("prof2", 200), ("sec", 200)):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, code, user)
        self.login("prof2")
        self.assertNotContains(self.client.get(url), "Ana")
        self.assertEqual(self.client.get(reverse("workshops:edit", args=[w.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("workshops:export", args=[w.pk])).status_code, 403)
        self.assertEqual(self.join(w, user="resp_bea", student=self.bea).status_code, 404)
        self.login("sec")
        self.assertContains(self.client.get(url), "Ana")

    def test_closed_or_late_signups_are_refused(self):
        w = self.published(capacity=5)
        self.login("prof")
        self.client.post(reverse("workshops:toggle", args=[w.pk]))
        self.join(w)
        self.assertFalse(Signup.objects.exists())
        Workshop.objects.filter(pk=w.pk).update(closed=False, signup_until=timezone.localdate() - dt.timedelta(days=1))
        self.join(w)
        self.assertFalse(Signup.objects.exists())

    def test_school_cancels_with_reason_and_exports(self):
        w = self.published(capacity=5)
        self.join(w)
        self.login("prof")
        self.assertIn("Ana", self.client.get(reverse("workshops:export", args=[w.pk])).content.decode("utf-8"))
        s = Signup.objects.get()
        self.client.post(reverse("workshops:cancel", args=[s.pk]), {"motivo": "Horário mudou para a manhã."})
        note = Notification.objects.get(user=self.resp, title__startswith="Inscrição cancelada")
        self.assertIn("Horário mudou", note.body)
