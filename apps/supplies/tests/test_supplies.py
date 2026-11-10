"""Lista de materiais: montar, colar, alertas legais, revisão, publicação com aviso, "já tenho" e permissões."""

import datetime as dt

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear
from apps.communication.models import Notification
from apps.communication.tests.test_communication import CommunicationBase
from apps.core.models import Role, User

from ..models import SupplyCheck, SupplyItem, SupplyList
from ..services import item_warnings, parse_line, parse_text, pending_for_family


class ParseAndWarningTests(SimpleTestCase):
    def test_reads_quantity_unit_numbering_and_optional(self):
        self.assertEqual(parse_line("3) 02 - cadernos brochura de 96 folhas;"),
                         {"name": "Cadernos brochura de 96 folhas", "quantity": 2, "unit": "", "optional": False})
        self.assertEqual(parse_line("• 1 cx de lápis de cor (opcional)"),
                         {"name": "Lápis de cor", "quantity": 1, "unit": "caixa", "optional": True})
        self.assertEqual(parse_line("2x tubos de cola")["unit"], "tubos")
        self.assertEqual(parse_line("100 folhas sulfite")["unit"], "folhas")
        self.assertEqual(parse_line("1 pote plástico"),  # sem "de": não é unidade
                         {"name": "Pote plástico", "quantity": 1, "unit": "", "optional": False})

    def test_skips_titles_blank_and_number_only_lines(self):
        text = "LISTA DE MATERIAIS 2027\n\nMaterial de artes:\n1 tesoura sem ponta\n12\n- \n2 borrachas"
        self.assertEqual([p["name"] for p in parse_text(text)], ["Tesoura sem ponta", "Borrachas"])

    def test_collective_use_and_brand_warnings(self):
        def warns(name, notes=""):
            return item_warnings(SupplyItem(name=name, notes=notes))

        self.assertIn("Lei 12.886/2013", warns("Papel higiênico")[0])
        self.assertTrue(warns("Copos descartáveis"))
        self.assertTrue(warns("Giz branco"))
        self.assertTrue(warns("Pincel atômico azul"))
        self.assertFalse(warns("Giz de cera grosso"))
        self.assertFalse(warns("Caderno de desenho"))
        self.assertIn("Código de Defesa do Consumidor", warns("Caderno", "marca Tilibra")[0])
        self.assertFalse(warns("Lápis", "qualquer marca"))


class SupplyListTests(CommunicationBase):
    def create(self, user="prof", **extra):
        self.login(user)
        data = {"title": "Lista de materiais — 1º ano", "school_year": self.year.pk, "grade": "1º ano",
                "class_groups": [self.turma.pk], **extra}
        self.client.post(reverse("supplies:create"), data)
        return SupplyList.objects.order_by("-pk").first()

    def fill(self, lst):
        self.client.post(reverse("supplies:paste", args=[lst.pk]),
                         {"texto": "2 cadernos de 96 folhas\n1 caixa de lápis de cor\n1 tesoura (opcional)"})

    def publish(self, lst, user="coord"):
        self.login(user)
        return self.client.post(reverse("supplies:publish", args=[lst.pk]))

    def test_teacher_builds_submits_and_coordination_publishes_with_family_notice(self):
        lst = self.create()
        self.assertEqual((lst.created_by, lst.status), (self.prof, "rascunho"))
        self.fill(lst)
        self.assertEqual(list(lst.items.values_list("quantity", "unit")), [(2, ""), (1, "caixa"), (1, "")])
        self.client.post(reverse("supplies:item_add", args=[lst.pk]), {"quantity": 1, "name": "Papel higiênico"})
        page = self.client.get(reverse("supplies:detail", args=[lst.pk]))
        self.assertContains(page, "Lei 12.886/2013")
        self.assertContains(page, "1 material com alerta")
        self.assertEqual(self.publish(lst, "prof").status_code, 403)  # professor não publica
        self.login("prof")
        self.client.post(reverse("supplies:submit", args=[lst.pk]))
        lst.refresh_from_db()
        self.assertEqual(lst.status, "revisao")
        self.assertTrue(Notification.objects.filter(user=self.coord, title__contains="para revisar").exists())
        # em revisão o professor não mexe mais
        self.assertEqual(self.client.post(reverse("supplies:item_add", args=[lst.pk]),
                                          {"quantity": 1, "name": "Régua"}).status_code, 403)
        self.login("coord")
        self.assertContains(self.client.get(reverse("pending_center")), "Listas de materiais para revisar")
        self.publish(lst)
        lst.refresh_from_db()
        self.assertEqual((lst.status, lst.published_by, lst.revision), ("publicada", self.coord, 1))
        self.assertTrue(Notification.objects.filter(user=self.resp, student=self.ana,
                                                    title__contains="Lista de materiais").exists())
        self.assertTrue(Notification.objects.filter(user=self.prof, title__contains="publicada").exists())

    def test_drafts_are_hidden_from_families_and_other_schools(self):
        lst = self.create()
        self.fill(lst)
        self.login("resp")
        self.assertEqual(self.client.get(reverse("supplies:detail", args=[lst.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("supplies:index")), lst.title)
        self.publish(lst)
        self.login("resp_b")
        self.assertEqual(self.client.get(reverse("supplies:detail", args=[lst.pk])).status_code, 404)
        self.login("prof_b")
        self.assertEqual(self.client.get(reverse("supplies:detail", args=[lst.pk])).status_code, 404)

    def test_teacher_sees_only_own_drafts(self):
        other = User.objects.create_user(username="prof2", password="senha-forte-1", role=Role.PROFESSOR,
                                         school=self.school)
        lst = self.create(class_groups=[self.turma_b.pk])  # turma em que prof não leciona: criou, então vê
        self.assertEqual(self.client.get(reverse("supplies:detail", args=[lst.pk])).status_code, 200)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("supplies:detail", args=[lst.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("supplies:item_add", args=[lst.pk]),
                                          {"quantity": 1, "name": "Régua"}).status_code, 403)

    def test_family_marks_what_it_has_privately_and_pending_follows(self):
        lst = self.create(deliver_by=(timezone.localdate() + dt.timedelta(days=20)).isoformat())
        self.fill(lst)
        self.publish(lst)
        self.login("resp")
        self.assertContains(self.client.get(reverse("supplies:index")), "0 de 2")
        self.assertContains(self.client.get(reverse("pending_center")), "Listas de materiais com itens a providenciar")
        self.assertEqual(pending_for_family(self.resp), 1)
        first = lst.items.first()
        self.client.post(reverse("supplies:checks", args=[lst.pk]), {"estudante": self.ana.pk, "item": [first.pk]})
        self.assertEqual(SupplyCheck.objects.filter(student=self.ana).count(), 1)
        self.assertContains(self.client.get(reverse("supplies:index")), "1 de 2")
        # outra criança: recusado
        self.assertEqual(self.client.post(reverse("supplies:checks", args=[lst.pk]),
                                          {"estudante": self.bea.pk, "tudo": "1"}).status_code, 403)
        self.client.post(reverse("supplies:checks", args=[lst.pk]), {"estudante": self.ana.pk, "tudo": "1"})
        self.assertEqual(SupplyCheck.objects.filter(student=self.ana).count(), 3)
        self.assertEqual(pending_for_family(self.resp), 0)
        # desmarcar
        self.client.post(reverse("supplies:checks", args=[lst.pk]), {"estudante": self.ana.pk})
        self.assertFalse(SupplyCheck.objects.exists())
        # a escola não vê as anotações
        self.login("coord")
        page = self.client.get(reverse("supplies:detail", args=[lst.pk]))
        self.assertNotContains(page, 'name="item"')
        self.assertNotContains(page, "Salvar o que j")

    def test_return_with_note_tells_the_teacher(self):
        lst = self.create()
        self.fill(lst)
        self.client.post(reverse("supplies:submit", args=[lst.pk]))
        self.login("coord")
        self.client.post(reverse("supplies:return", args=[lst.pk]), {"observacao": ""})
        lst.refresh_from_db()
        self.assertEqual(lst.status, "revisao")  # sem observação, não devolve
        self.client.post(reverse("supplies:return", args=[lst.pk]), {"observacao": "Tirar a tesoura"})
        lst.refresh_from_db()
        self.assertEqual((lst.status, lst.review_note), ("rascunho", "Tirar a tesoura"))
        self.assertTrue(Notification.objects.filter(user=self.prof, title__contains="devolvida").exists())
        self.login("prof")
        self.assertContains(self.client.get(reverse("pending_center")), "devolvidas com observação")
        self.assertContains(self.client.get(reverse("supplies:detail", args=[lst.pk])), "Tirar a tesoura")

    def test_change_notice_unpublish_text_and_copy(self):
        lst = self.create()
        self.fill(lst)
        self.publish(lst)
        self.client.post(reverse("supplies:notify", args=[lst.pk]))
        self.assertEqual(Notification.objects.filter(user=self.resp, student=self.ana).count(), 2)
        self.login("resp")
        text = self.client.get(reverse("supplies:text", args=[lst.pk]))
        self.assertEqual(text["Content-Type"], "text/plain; charset=utf-8")
        self.assertIn("[ ] 1 caixa de lápis de cor", text.content.decode())
        self.assertIn("(opcional)", text.content.decode())
        self.login("coord")
        self.client.post(reverse("supplies:duplicate", args=[lst.pk]))
        copy = SupplyList.objects.order_by("-pk").first()
        self.assertEqual((copy.status, copy.class_groups.count(), copy.items.count()), ("rascunho", 0, 3))
        self.client.post(reverse("supplies:unpublish", args=[lst.pk]))
        self.login("resp")
        self.assertEqual(self.client.get(reverse("supplies:detail", args=[lst.pk])).status_code, 404)

    def test_classes_must_belong_to_the_list_year_and_next_year_lists_show_to_everyone(self):
        nxt = SchoolYear.objects.create(school=self.school, name="2027")
        lst = self.create(school_year=nxt.pk)  # turma de 2026 numa lista de 2027
        self.assertIsNone(lst)
        cg = ClassGroup.objects.create(school=self.school, school_year=nxt, name="2º Ano A")
        lst = self.create(title="Lista 2º ano 2027", school_year=nxt.pk, class_groups=[cg.pk])
        self.fill(lst)
        self.publish(lst)
        self.assertFalse(Notification.objects.filter(user=self.resp).exists())  # turma sem estudantes
        self.login("resp")
        self.assertContains(self.client.get(reverse("supplies:index")), "Lista 2º ano 2027")
        self.assertEqual(self.client.get(reverse("supplies:detail", args=[lst.pk])).status_code, 200)
