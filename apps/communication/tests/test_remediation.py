from django.urls import reverse

from apps.communication.forms import ThreadForm
from apps.communication.models import Notification

from .test_communication import CommunicationBase


class NotificationReadTests(CommunicationBase):
    def test_listing_notifications_does_not_mark_them_read(self):
        notification = Notification.objects.create(
            school=self.school,
            user=self.resp,
            kind=Notification.Kind.ANNOUNCEMENT,
            title="Aviso importante",
        )
        self.login("resp")
        resp = self.client.get(reverse("communication:notification_list"))
        self.assertEqual(resp.status_code, 200)
        notification.refresh_from_db()
        self.assertFalse(notification.is_read)

    def test_opening_notification_requires_post_and_marks_read(self):
        notification = Notification.objects.create(
            school=self.school,
            user=self.resp,
            kind=Notification.Kind.ANNOUNCEMENT,
            title="Aviso importante",
        )
        self.login("resp")
        url = reverse("communication:notification_read", args=[notification.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        notification.refresh_from_db()
        self.assertFalse(notification.is_read)
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)


class ThreadStudentScopeTests(CommunicationBase):
    def test_professional_cannot_link_guardian_to_unrelated_student(self):
        form = ThreadForm(
            user=self.coord,
            data={
                "recipient": self.resp.pk,
                "student": self.bea.pk,
                "title": "Conversa indevida",
                "body": "Mensagem",
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn("recipient", form.errors)
        self.assertIn("vinculado", " ".join(form.errors["recipient"]))
