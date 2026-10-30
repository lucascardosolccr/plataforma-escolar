"""Segunda rodada do redesign (Prompt 12): o que mudou de comportamento.

Cada teste aqui reprovava antes da rodada ou protege uma regra nova:
scripts só por arquivo (CSP sem 'unsafe-inline'), ajuda por perfil sem
links para telas proibidas, botões de notas só onde o professor leciona,
ordenação no servidor que ignora valor inventado na URL, seleção em lote
que nunca alcança a notificação de outra pessoa e o filtro de conversas
não lidas.
"""

import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.communication.models import Message, Notification, Thread
from apps.core.models import Role, School, User
from apps.core.navigation import all_visible_urls
from apps.pedagogy.models import Evaluation, Occurrence
from apps.registry.models import Enrollment, GuardianLink, Student

PW = "senha-forte-1"
TEMPLATES = Path(settings.BASE_DIR) / "templates"


class NoInlineScriptTests(SimpleTestCase):
    """Sem script embutido, a CSP pode exigir script-src 'self'."""

    def test_templates_have_no_inline_script_or_handler(self):
        handler = re.compile(r"\son[a-z]+\s*=\s*[\"']", re.I)
        inline = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.I)
        for path in TEMPLATES.rglob("*.html"):
            html = path.read_text(encoding="utf-8")
            with self.subTest(template=str(path.relative_to(TEMPLATES))):
                self.assertIsNone(handler.search(html))
                self.assertIsNone(inline.search(html))

    def test_csp_forbids_inline_script(self):
        from apps.core.middleware import ContentSecurityPolicyMiddleware

        script = [d for d in ContentSecurityPolicyMiddleware.POLICY.split("; ") if d.startswith("script-src")][0]
        self.assertEqual(script, "script-src 'self'")


class Round2Base(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        year = SchoolYear.objects.create(school=self.school, name="2026")
        self.turma = ClassGroup.objects.create(school=self.school, school_year=year, name="5º A")
        self.mat = Subject.objects.create(school=self.school, name="Matemática")
        self.geo = Subject.objects.create(school=self.school, name="Geografia")

        def mk(username, role):
            return User.objects.create_user(username=username, password=PW, role=role, school=self.school,
                                            first_name=username.title())

        self.users = {r: mk(r, r) for r in Role.values}
        self.prof = self.users[Role.PROFESSOR]
        self.colega = mk("colega", Role.PROFESSOR)
        TeacherAssignment.objects.create(school=self.school, school_year=year, teacher=self.prof,
                                         class_group=self.turma, subject=self.mat)
        TeacherAssignment.objects.create(school=self.school, school_year=year, teacher=self.colega,
                                         class_group=self.turma, subject=self.geo)
        self.ana = Student.objects.create(school=self.school, first_name="Ana", last_name="Souza")
        self.bia = Student.objects.create(school=self.school, first_name="Bia", last_name="Lima")
        for s in (self.ana, self.bia):
            Enrollment.objects.create(school=self.school, student=s, class_group=self.turma, school_year=year)
        GuardianLink.objects.create(school=self.school, guardian=self.users[Role.RESPONSAVEL], student=self.ana,
                                    status="aprovado")

    def login(self, user):
        self.client.logout()
        self.assertTrue(self.client.login(username=user.username, password=PW))


class HelpPageTests(Round2Base):
    def test_every_role_opens_help_and_links_only_to_visible_screens(self):
        for role, user in self.users.items():
            if role == Role.ESTUDANTE:
                continue  # conta de estudante precisa da ficha ligada; coberta abaixo
            with self.subTest(perfil=role):
                self.login(user)
                resp = self.client.get(reverse("help"))
                self.assertEqual(resp.status_code, 200)
                visible = set(all_visible_urls(user))
                for guide in resp.context["guides"]:
                    for step in guide["steps"]:
                        if step["url"]:
                            self.assertIn(step["url"], visible)
                self.assertTrue(resp.context["faq"])

    def test_help_is_in_menu_and_search_for_everyone(self):
        self.login(self.users[Role.RESPONSAVEL])
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, f'href="{reverse("help")}"')
        self.assertIn(reverse("help"), all_visible_urls(self.users[Role.RESPONSAVEL]))

    def test_family_guides_are_not_teacher_guides(self):
        self.login(self.users[Role.RESPONSAVEL])
        titles = [g["title"] for g in self.client.get(reverse("help")).context["guides"]]
        self.assertIn("Justificar uma falta", titles)
        self.assertNotIn("Fazer a chamada do dia", titles)


class EvaluationListTests(Round2Base):
    def setUp(self):
        super().setUp()
        self.minha = Evaluation.objects.create(school=self.school, subject=self.mat, class_group=self.turma,
                                               title="Prova de frações", date=date(2026, 3, 10), created_by=self.prof)
        self.alheia = Evaluation.objects.create(school=self.school, subject=self.geo, class_group=self.turma,
                                                title="Mapa do bairro", date=date(2026, 3, 12), created_by=self.colega)

    def test_grade_buttons_only_where_the_teacher_teaches(self):
        """Antes, "Notas" e "Editar" apareciam na avaliação do colega e davam 403."""
        self.login(self.prof)
        resp = self.client.get(reverse("pedagogy:evaluation_list"))
        self.assertContains(resp, reverse("pedagogy:evaluation_grade", args=[self.minha.pk]))
        self.assertNotContains(resp, reverse("pedagogy:evaluation_grade", args=[self.alheia.pk]))
        self.assertNotContains(resp, reverse("pedagogy:evaluation_edit", args=[self.alheia.pk]))
        self.assertContains(resp, "De outro professor")

    def test_scope_filter_shows_only_own_subjects(self):
        self.login(self.prof)
        resp = self.client.get(reverse("pedagogy:evaluation_list") + "?escopo=minhas")
        self.assertContains(resp, "Prova de frações")
        self.assertNotContains(resp, "Mapa do bairro")

    def test_server_sort_and_invented_sort_value(self):
        self.login(self.users[Role.COORDENACAO])
        url = reverse("pedagogy:evaluation_list")
        rows = [r["eval"].title for r in self.client.get(url + "?ordem=titulo").context["rows"]]
        self.assertEqual(rows, ["Mapa do bairro", "Prova de frações"])
        rows = [r["eval"].title for r in self.client.get(url + "?ordem=-titulo").context["rows"]]
        self.assertEqual(rows, ["Prova de frações", "Mapa do bairro"])
        # Valor que não está na lista volta ao padrão (data mais recente primeiro), sem erro.
        resp = self.client.get(url + "?ordem=password;drop")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r["eval"].title for r in resp.context["rows"]], ["Mapa do bairro", "Prova de frações"])

    def test_sort_header_keeps_filters_and_announces_order(self):
        self.login(self.users[Role.COORDENACAO])
        resp = self.client.get(reverse("pedagogy:evaluation_list") + "?status=rascunho&ordem=titulo&pagina=2")
        html = resp.content.decode()
        self.assertIn('aria-sort="ascending"', html)
        link = re.search(r'<a class="th-sort" href="\?([^"]*)" title="Ordenar por avaliação"', html).group(1)
        self.assertIn("status=rascunho", link)
        self.assertIn("ordem=-titulo", link)
        self.assertNotIn("pagina=", link)


class OccurrenceSearchTests(Round2Base):
    def test_search_by_student_name(self):
        for s in (self.ana, self.bia):
            Occurrence.objects.create(school=self.school, student=s, description="Fato", date=date(2026, 4, 1),
                                      recorded_by=self.prof)
        self.login(self.users[Role.COORDENACAO])
        resp = self.client.get(reverse("pedagogy:occurrence_list") + "?q=souza")
        self.assertEqual([o.student for o in resp.context["occurrences"]], [self.ana])


class NotificationBulkTests(Round2Base):
    def test_mark_selected_read_never_touches_someone_else(self):
        me, other = self.users[Role.RESPONSAVEL], self.users[Role.SECRETARIA]
        mine = [Notification.objects.create(school=self.school, user=me, kind="comunicado", title=f"A{i}")
                for i in range(3)]
        alheia = Notification.objects.create(school=self.school, user=other, kind="comunicado", title="B")
        self.login(me)
        self.client.post(reverse("communication:notification_read_selected"),
                         {"ids": [mine[0].pk, mine[1].pk, alheia.pk, "x"]})
        self.assertEqual(sorted(Notification.objects.filter(user=me, is_read=True).values_list("pk", flat=True)),
                         sorted([mine[0].pk, mine[1].pk]))
        alheia.refresh_from_db()
        self.assertFalse(alheia.is_read)

    def test_unread_filter(self):
        me = self.users[Role.RESPONSAVEL]
        Notification.objects.create(school=self.school, user=me, kind="comunicado", title="Lida", is_read=True)
        Notification.objects.create(school=self.school, user=me, kind="comunicado", title="Nova")
        self.login(me)
        resp = self.client.get(reverse("communication:notification_list") + "?situacao=nao_lidas")
        self.assertEqual([n.title for n in resp.context["notifications"]], ["Nova"])


class ThreadUnreadFilterTests(Round2Base):
    def test_unread_means_a_message_from_someone_else_not_yet_read(self):
        me, prof = self.users[Role.RESPONSAVEL], self.prof

        def conversa(title):
            t = Thread.objects.create(school=self.school, title=title, created_by=me)
            t.participants.add(me, prof)
            return t

        lida = conversa("Lida")
        Message.objects.create(thread=lida, sender=prof, body="oi")
        lida.messages.update(read_at="2026-04-01T10:00:00Z")
        so_minha = conversa("Só minha, sem resposta")
        Message.objects.create(thread=so_minha, sender=me, body="olá")  # minha e ainda não lida pelo professor
        nova = conversa("Resposta nova")
        Message.objects.create(thread=nova, sender=me, body="pergunta")
        Message.objects.create(thread=nova, sender=prof, body="resposta")
        self.login(me)
        resp = self.client.get(reverse("communication:thread_list") + "?leitura=nao_lidas")
        self.assertEqual([t["thread"].title for t in resp.context["threads"]], ["Resposta nova"])


class DateFieldsRoundTripTests(Round2Base):
    """O campo de data do navegador só aceita AAAA-MM-DD.

    A ficha mostrava "17/02/2020": o navegador descartava o valor, o campo
    aparecia vazio e salvar a ficha apagava a data de nascimento.
    """

    def test_student_edit_shows_birth_date_in_iso_format(self):
        self.ana.birth_date = date(2020, 2, 17)
        self.ana.save(update_fields=["birth_date"])
        self.login(self.users[Role.SECRETARIA])
        resp = self.client.get(reverse("student_edit", args=[self.ana.pk]))
        self.assertContains(resp, 'value="2020-02-17"')
        self.assertNotContains(resp, 'value="17/02/2020"')

    def test_every_date_widget_renders_iso(self):
        from django import forms as djforms

        from apps.academics import forms as academics_forms
        from apps.registry import forms as registry_forms

        for module in (academics_forms, registry_forms):
            for form_class in vars(module).values():
                if not (isinstance(form_class, type) and issubclass(form_class, djforms.BaseForm)):
                    continue
                for name, field in form_class.base_fields.items():
                    widget = field.widget
                    if isinstance(widget, djforms.DateInput) and widget.input_type == "date":
                        with self.subTest(form=form_class.__name__, field=name):
                            self.assertEqual(widget.format, "%Y-%m-%d")
