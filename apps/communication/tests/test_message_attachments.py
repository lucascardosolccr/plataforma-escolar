"""Anexo nas mensagens entre família e escola (Prompt 15 §6.3).

O arquivo passa pela mesma validação dos anexos de atividade (extensão,
tamanho e conteúdo) e só é baixado por quem pode ver a conversa.
"""

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from ..models import Message, Thread
from .test_communication import CommunicationBase


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="escola-msg-media-"))
class MessageAttachmentTests(CommunicationBase):
    def _start(self, attachment=None):
        self.login("resp")
        data = {"student": self.ana.pk, "recipient": self.prof.pk, "title": "Atestado", "body": "Segue o atestado."}
        if attachment:
            data["attachment"] = attachment
        self.client.post(reverse("communication:thread_create"), data)
        return Thread.objects.filter(title="Atestado").first()

    def test_family_sends_attachment_and_participant_downloads(self):
        thread = self._start(SimpleUploadedFile("atestado.pdf", b"%PDF-1.4 conteudo"))
        msg = Message.objects.get(thread=thread)
        self.assertEqual(msg.attachment_name, "atestado.pdf")
        self.assertTrue(msg.attachment.name.startswith("messages/"))
        self.assertNotIn("atestado", msg.attachment.name)  # nome no disco é aleatório
        url = reverse("communication:message_attachment", args=[msg.pk])
        page = self.client.get(reverse("communication:thread_detail", args=[thread.pk]))
        self.assertContains(page, url)
        self.login("prof")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertEqual(b"".join(resp.streaming_content), b"%PDF-1.4 conteudo")

    def test_reply_with_attachment(self):
        thread = self._start()
        self.login("prof")
        self.client.post(reverse("communication:thread_detail", args=[thread.pk]),
                         {"body": "Recebido. Envio o roteiro.", "attachment": SimpleUploadedFile("roteiro.pdf", b"%PDF-1.4 r")})
        msg = Message.objects.get(thread=thread, sender=self.prof)
        self.assertEqual(msg.attachment_name, "roteiro.pdf")

    def test_executable_disguised_is_refused_and_nothing_is_saved(self):
        thread = self._start(SimpleUploadedFile("laudo.pdf", b"MZ\x90\x00 executavel"))
        self.assertIsNone(thread)
        self.assertFalse(Message.objects.exists())

    def test_non_participants_cannot_download(self):
        thread = self._start(SimpleUploadedFile("atestado.pdf", b"%PDF-1.4 conteudo"))
        url = reverse("communication:message_attachment", args=[Message.objects.get(thread=thread).pk])
        self.login("adm")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login("resp_b")  # outra escola
        self.assertEqual(self.client.get(url).status_code, 404)
