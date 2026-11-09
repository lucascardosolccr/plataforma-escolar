"""Reserva de espaços e equipamentos: sobreposição, quem reserva, quem cancela e o aviso de cancelamento."""

import datetime as dt

from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification
from apps.communication.tests.test_communication import CommunicationBase

from ..models import Booking, Resource


class BookingTests(CommunicationBase):
    def setUp(self):
        super().setUp()
        self.lab = Resource.objects.create(school=self.school, name="Sala de informática")
        self.day = timezone.localdate() + dt.timedelta(days=1)

    def book(self, user="prof", start="08:00", end="09:00", **extra):
        self.login(user)
        data = {"resource": self.lab.pk, "day": self.day.isoformat(), "start": start, "end": end, **extra}
        return self.client.post(reverse("booking:create"), data)

    def test_overlap_is_refused_and_touching_slots_fit(self):
        self.book()
        self.assertContains(self.book("dir", "08:30", "09:30"), "já está reservado das 08:00 às 09:00")
        self.book("dir", "09:00", "10:00")
        self.book("dir", "07:00", "08:00")
        self.assertEqual(Booking.objects.count(), 3)

    def test_invalid_times_and_days(self):
        self.book(start="10:00", end="09:00")
        self.book(day=(timezone.localdate() - dt.timedelta(days=1)).isoformat())
        self.book(day=(timezone.localdate() + dt.timedelta(days=91)).isoformat())
        self.assertFalse(Booking.objects.exists())

    def test_other_schools_resource_and_teacher_class_scope(self):
        other = Resource.objects.create(school=self.school_b, name="Quadra")
        self.book(resource=other.pk)
        self.book(class_group=self.turma_b.pk)  # o professor não dá aula nessa turma
        self.assertFalse(Booking.objects.exists())
        self.book(class_group=self.turma.pk, purpose="Pesquisa")
        self.assertEqual(Booking.objects.get().class_group, self.turma)

    def test_family_cannot_book_or_see(self):
        self.login("resp")
        self.assertEqual(self.client.get(reverse("booking:agenda")).status_code, 403)
        self.assertEqual(self.book("resp").status_code, 403)
        self.assertEqual(self.client.get(reverse("booking:resources")).status_code, 403)

    def test_cancel_frees_the_slot_and_manager_cancel_notifies(self):
        self.book()
        b = Booking.objects.get()
        self.login("coord")
        self.client.post(reverse("booking:cancel", args=[b.pk]))
        b.refresh_from_db()
        self.assertIsNotNone(b.canceled_at)
        self.assertTrue(Notification.objects.filter(user=self.prof, title__startswith="Sua reserva foi cancelada"))
        self.book("dir")  # horário livre de novo
        self.assertEqual(Booking.objects.filter(canceled_at__isnull=True).count(), 1)

    def test_teacher_cancels_only_own(self):
        self.book("dir")
        b = Booking.objects.get()
        self.login("prof")
        self.assertEqual(self.client.post(reverse("booking:cancel", args=[b.pk])).status_code, 403)

    def test_agenda_and_resources(self):
        self.book(purpose="Pesquisa sobre o bairro")
        self.login("sec")
        page = self.client.get(reverse("booking:agenda") + f"?dia={self.day.isoformat()}")
        self.assertContains(page, "Pesquisa sobre o bairro")
        self.assertContains(self.client.get(reverse("booking:agenda") + "?dia=abc"), "Sala de informática")
        self.client.post(reverse("booking:resources"), {"name": "sala de informática", "kind": "espaco"})
        self.assertEqual(Resource.objects.filter(school=self.school).count(), 1)  # nome repetido
        self.client.post(reverse("booking:resources"), {"name": "Projetor 1", "kind": "equipamento", "active": "on"})
        self.assertTrue(Resource.objects.filter(name="Projetor 1").exists())
        self.client.post(reverse("booking:resource_edit", args=[self.lab.pk]), {"name": "Sala de informática",
                                                                              "kind": "espaco"})
        self.lab.refresh_from_db()
        self.assertFalse(self.lab.active)
        self.assertEqual(self.book("prof").status_code, 200)  # fora de uso: não aparece para reservar
