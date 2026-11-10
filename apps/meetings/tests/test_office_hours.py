"""Horários de atendimento: a equipe abre, a família da turma marca, e cada horário marcado vira uma reunião."""

import datetime as dt

from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification
from apps.communication.tests.test_communication import CommunicationBase
from apps.core.models import Role, User
from apps.registry.models import Enrollment, GuardianLink, Student

from ..models import Meeting, OfficeHours, OfficeSlot


class OfficeHoursTests(CommunicationBase):
    def open_hours(self, **extra):
        self.login("prof")
        day = timezone.localdate() + dt.timedelta(days=3)
        data = {"title": "Reunião de pais", "day": day.isoformat(), "start": "14:00", "end": "15:00",
                "slot_minutes": "15", "location": "Sala 5", "class_groups": [self.turma.pk], **extra}
        return self.client.post(reverse("office:create"), data)

    def book(self, hours, slot=None, user="resp", student=None, topic=""):
        self.login(user)
        slot = slot or hours.slots.filter(student__isnull=True).first()
        return self.client.post(reverse("office:book", args=[hours.pk]),
                                {"student": (student or self.ana).pk, "slot": slot.pk, "topic": topic})

    def test_teacher_opens_hours_for_own_class_and_families_are_told(self):
        self.open_hours()
        hours = OfficeHours.objects.get()
        self.assertEqual([timezone.localtime(s.starts_at).strftime("%H:%M") for s in hours.slots.all()],
                         ["14:00", "14:15", "14:30", "14:45"])
        self.assertTrue(Notification.objects.filter(user=self.resp, kind="reuniao", title__contains="Horários").exists())
        self.open_hours(class_groups=[self.turma_b.pk])  # turma de outro professor
        self.open_hours(day=(timezone.localdate() - dt.timedelta(days=1)).isoformat())
        self.open_hours(end="13:00")
        self.assertEqual(OfficeHours.objects.count(), 1)

    def test_family_books_and_it_becomes_a_meeting_without_seeing_other_families(self):
        self.open_hours()
        hours = OfficeHours.objects.get()
        caio = Student.objects.create(school=self.school, first_name="Caio")
        Enrollment.objects.create(school=self.school, student=caio, class_group=self.turma, school_year=self.year)
        resp2 = User.objects.create_user(username="resp2", password="senha-forte-1", role=Role.RESPONSAVEL,
                                         school=self.school)
        GuardianLink.objects.create(school=self.school, guardian=resp2, student=caio, status="aprovado")
        first = hours.slots.first()
        self.book(hours, slot=first, user="resp2", student=caio)
        self.book(hours, slot=first, topic="Notas de Matemática")  # já ocupado
        self.assertEqual(OfficeSlot.objects.filter(student=self.ana).count(), 0)
        self.book(hours, topic="Notas de Matemática")
        slot = OfficeSlot.objects.get(student=self.ana)
        meeting = slot.meeting
        self.assertEqual((meeting.student, meeting.created_by, meeting.agenda), (self.ana, self.prof,
                                                                                 "Notas de Matemática"))
        self.assertEqual(set(meeting.participants.values_list("username", flat=True)), {"prof", "resp"})
        self.assertTrue(Notification.objects.filter(user=self.prof, title__startswith="Reunião marcada").exists())
        self.book(hours)  # um horário por estudante
        self.assertEqual(OfficeSlot.objects.filter(student=self.ana).count(), 1)
        page = self.client.get(reverse("office:detail", args=[hours.pk]))
        self.assertContains(page, "Notas de Matemática")
        self.assertNotContains(page, "Caio")
        self.login("prof")
        self.assertContains(self.client.get(reverse("office:detail", args=[hours.pk])), "Caio")

    def test_access(self):
        self.open_hours()
        hours = OfficeHours.objects.get()
        url = reverse("office:detail", args=[hours.pk])
        bea_parent = User.objects.create_user(username="resp_bea", password="senha-forte-1",
                                              role=Role.RESPONSAVEL, school=self.school)
        GuardianLink.objects.create(school=self.school, guardian=bea_parent, student=self.bea, status="aprovado")
        User.objects.create_user(username="prof2", password="senha-forte-1", role=Role.PROFESSOR,
                                         school=self.school)
        for user, code in (("resp_bea", 404), ("resp_b", 404), ("prof2", 403), ("dir", 200), ("resp", 200)):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, code, user)
        self.login("resp_bea")
        self.assertEqual(self.book(hours, user="resp_bea", student=self.bea).status_code, 404)
        self.assertFalse(OfficeSlot.objects.filter(student__isnull=False).exists())
        self.assertNotContains(self.client.get(reverse("office:list")), "Reunião de pais")

    def test_release_by_family_or_host_and_meeting_cancel_free_the_slot(self):
        self.open_hours()
        hours = OfficeHours.objects.get()
        self.book(hours)
        slot = OfficeSlot.objects.get(student=self.ana)
        meeting = slot.meeting
        self.client.post(reverse("office:release", args=[slot.pk]))
        slot.refresh_from_db()
        meeting.refresh_from_db()
        self.assertTrue(slot.free)
        self.assertEqual(meeting.status, Meeting.Status.CANCELED)
        self.assertTrue(Notification.objects.filter(user=self.prof, title__startswith="Reunião cancelada").exists())
        self.book(hours)
        slot = OfficeSlot.objects.get(student=self.ana)
        self.login("prof")
        self.client.post(reverse("meetings:cancel", args=[slot.meeting_id]), {"reason": "Fiquei doente."})
        slot.refresh_from_db()
        self.assertTrue(slot.free)
        self.assertTrue(Notification.objects.filter(user=self.resp, body__contains="Fiquei doente").exists())

    def test_booked_hours_keep_their_times_and_cannot_be_deleted(self):
        self.open_hours()
        hours = OfficeHours.objects.get()
        self.book(hours)
        self.login("prof")
        self.client.post(reverse("office:edit", args=[hours.pk]), {
            "title": "Reunião de pais (sala nova)", "day": hours.day.isoformat(), "start": "08:00", "end": "09:00",
            "slot_minutes": "30", "location": "Sala 7", "class_groups": [self.turma.pk]})
        hours.refresh_from_db()
        self.assertEqual((hours.title, hours.start, hours.slots.count()), ("Reunião de pais (sala nova)",
                                                                           dt.time(14, 0), 4))
        self.client.post(reverse("office:delete", args=[hours.pk]))
        self.assertTrue(OfficeHours.objects.exists())

    def test_closed_or_past_slots_cannot_be_booked(self):
        self.open_hours()
        hours = OfficeHours.objects.get()
        first = hours.slots.first()
        OfficeSlot.objects.filter(pk=first.pk).update(starts_at=timezone.now() - dt.timedelta(minutes=5))
        self.book(hours, slot=first)
        self.assertFalse(OfficeSlot.objects.filter(student=self.ana).exists())
        self.login("prof")
        self.client.post(reverse("office:toggle", args=[hours.pk]))
        self.book(hours)
        self.assertFalse(OfficeSlot.objects.filter(student=self.ana).exists())
