"""Achados e perdidos: registro, "é meu" com descrição, conferência, entrega, doação e privacidade."""

import datetime as dt
import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification
from apps.communication.tests.test_communication import CommunicationBase

from ..models import Claim, FoundItem

MEDIA = tempfile.mkdtemp()


def png():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buf, "PNG")
    return SimpleUploadedFile("casaco.png", buf.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=MEDIA)
class LostFoundTests(CommunicationBase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def register(self, user="prof", **extra):
        self.login(user)
        data = {"title": "Casaco azul-marinho", "category": "roupa", "details": "Tamanho 10, marca X",
                "place": "Quadra", "found_on": timezone.localdate().isoformat(), **extra}
        self.client.post(reverse("lostfound:create"), data)
        return FoundItem.objects.order_by("-pk").first()

    def test_teacher_registers_with_photo_and_family_sees_it(self):
        item = self.register(photo=png())
        self.assertEqual(item.registered_by, self.prof)
        self.assertTrue(item.photo)
        self.login("resp")
        self.assertContains(self.client.get(reverse("lostfound:list")), "Casaco azul-marinho")
        page = self.client.get(reverse("lostfound:item", args=[item.pk]))
        self.assertContains(page, "Tamanho 10")
        self.assertEqual(self.client.get(reverse("lostfound:photo", args=[item.pk])).status_code, 200)

    def test_valuables_hide_details_and_photo_from_families(self):
        item = self.register(title="iPhone com capinha de gato", category="eletronico", details="Tela trincada",
                             photo=png())
        self.login("resp")
        lst = self.client.get(reverse("lostfound:list"))
        self.assertNotContains(lst, "iPhone")
        page = self.client.get(reverse("lostfound:item", args=[item.pk]))
        self.assertNotContains(page, "Tela trincada")
        self.assertNotContains(page, "capinha de gato")
        self.assertEqual(self.client.get(reverse("lostfound:photo", args=[item.pk])).status_code, 404)

    def test_claim_needs_a_description_staff_confirms_and_others_are_told(self):
        item = self.register()
        self.login("resp")
        self.client.post(reverse("lostfound:claim", args=[item.pk]), {"descricao": "meu"})
        self.assertFalse(Claim.objects.exists())  # descrição curta demais
        self.client.post(reverse("lostfound:claim", args=[item.pk]), {"descricao": "Tem o nome Ana na etiqueta"})
        claim = Claim.objects.get()
        self.assertEqual(claim.student, self.ana)
        self.assertTrue(Notification.objects.filter(user=self.sec, title__contains="pedido de").exists())
        self.assertTrue(Notification.objects.filter(user=self.prof, title__contains="pedido de").exists())
        self.login("sec")
        self.assertContains(self.client.get(reverse("pending_center")), "pedidos para conferir")
        self.assertContains(self.client.get(reverse("lostfound:item", args=[item.pk])), "Tem o nome Ana")
        self.client.post(reverse("lostfound:return", args=[item.pk]), {"pedido": claim.pk})
        item.refresh_from_db()
        claim.refresh_from_db()
        self.assertEqual((item.status, claim.status), ("devolvido", "confirmado"))
        self.assertEqual(item.returned_to, "resp")
        self.login("resp")  # entregue: some da lista das famílias
        self.assertEqual(self.client.get(reverse("lostfound:item", args=[item.pk])).status_code, 404)

    def test_reject_claim_tells_the_family(self):
        item = self.register()
        self.login("resp")
        self.client.post(reverse("lostfound:claim", args=[item.pk]), {"descricao": "É verde com listras"})
        self.login("sec")
        self.client.post(reverse("lostfound:claim_reject", args=[Claim.objects.get().pk]))
        self.assertEqual(Claim.objects.get().status, "recusado")
        self.assertTrue(Notification.objects.filter(user=self.resp, body__contains="não confere").exists())

    def test_name_on_the_item_tells_only_that_family(self):
        item = self.register()
        self.login("prof")
        self.client.post(reverse("lostfound:owner", args=[item.pk]), {"estudante": self.ana.pk})
        n = Notification.objects.get(user=self.resp, title__startswith="Achados e perdidos")
        self.assertEqual(n.kind, "biblioteca")
        page = self.client.get(reverse("lostfound:item", args=[item.pk]))
        self.assertContains(page, "Dono identificado")
        self.login("resp")
        self.assertContains(self.client.get(reverse("lostfound:item", args=[item.pk])), "Está com o nome de Ana")

    def test_permissions(self):
        item = self.register()
        self.login("resp")
        self.assertEqual(self.client.get(reverse("lostfound:create")).status_code, 403)
        self.assertEqual(self.client.post(reverse("lostfound:return", args=[item.pk]),
                                          {"entregue_a": "Eu"}).status_code, 403)
        self.client.login(username="prof_b", password="senha-forte-1")  # outra escola
        self.assertEqual(self.client.get(reverse("lostfound:item", args=[item.pk])).status_code, 404)
        other = self.register(user="sec", title="Garrafa rosa")
        self.login("prof")  # não registrou e não é da gestão
        self.assertEqual(self.client.post(reverse("lostfound:return", args=[other.pk]),
                                          {"entregue_a": "Eu"}).status_code, 403)

    def test_old_items_donated_photo_deleted_and_hidden_from_families(self):
        old = self.register(photo=png())
        path = old.photo.path
        FoundItem.objects.filter(pk=old.pk).update(found_on=timezone.localdate() - dt.timedelta(days=61))
        waiting = self.register(title="Garrafa rosa")
        FoundItem.objects.filter(pk=waiting.pk).update(found_on=timezone.localdate() - dt.timedelta(days=70))
        Claim.objects.create(item=waiting, user=self.resp, description="Tem adesivo de estrela")
        self.login("prof")
        self.assertEqual(self.client.post(reverse("lostfound:donate_old")).status_code, 403)
        self.login("sec")
        self.client.post(reverse("lostfound:donate_old"))
        old.refresh_from_db()
        waiting.refresh_from_db()
        self.assertEqual((old.status, waiting.status), ("doado", "guardado"))  # com pedido aguardando, fica
        self.assertFalse(old.photo)
        import os

        self.assertFalse(os.path.exists(path))
