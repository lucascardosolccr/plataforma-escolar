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

    def test_templates_have_no_inline_style(self):
        for path in TEMPLATES.rglob("*.html"):
            html = path.read_text(encoding="utf-8")
            with self.subTest(template=str(path.relative_to(TEMPLATES))):
                self.assertNotRegex(html, r"\sstyle\s*=")
                self.assertNotRegex(html, r"<style[\s>]")

    def test_charts_have_no_inline_style(self):
        from apps.analytics import charts

        html = (charts.h_bars([{"label": "A", "value": 3}, {"label": "B", "value": 1, "below": True}])
                + charts.gauge(80, limit=25)
                + charts.bar_chart([{"label": "A", "value": 2}])
                + charts.line_chart([{"label": "a", "value": 1}, {"label": "b", "value": 2}]))
        self.assertNotIn("style=", html)
        self.assertIn('width="75.0"', charts.h_bars([{"label": "A", "value": 4}, {"label": "B", "value": 3}]))

    def test_csp_forbids_inline_style(self):
        from apps.core.middleware import ContentSecurityPolicyMiddleware

        style = [d for d in ContentSecurityPolicyMiddleware.POLICY.split("; ") if d.startswith("style-src")][0]
        self.assertEqual(style, "style-src 'self'")

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


class MoreServerSortTests(Round2Base):
    def test_guardian_list_sorts_by_name_both_ways(self):
        for first in ("Carla", "Beto"):
            User.objects.create_user(username=first.lower(), password=PW, role=Role.RESPONSAVEL,
                                     school=self.school, first_name=first)
        self.login(self.users[Role.SECRETARIA])
        url = reverse("guardian_list")
        names = [g.first_name for g in self.client.get(url + "?ordem=nome").context["guardians"]]
        self.assertEqual(names, sorted(names))
        names_desc = [g.first_name for g in self.client.get(url + "?ordem=-nome").context["guardians"]]
        self.assertEqual(names_desc, sorted(names, reverse=True))

    def test_assignment_search_and_invented_order(self):
        self.login(self.users[Role.SECRETARIA])
        resp = self.client.get(reverse("assignment_list") + "?q=geografia&ordem=xyz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([a.subject for a in resp.context["assignments"]], [self.geo])

    def test_user_list_role_filter_and_no_school_column(self):
        self.login(self.users[Role.ADMIN])
        resp = self.client.get(reverse("user_list") + "?perfil=professor&ordem=-usuario")
        self.assertEqual([u.username for u in resp.context["users"]], ["professor", "colega"])
        self.assertNotContains(resp, '<th scope="col">Escola</th>')


class LoginThrottleTests(Round2Base):
    """Limite de tentativas de login (contadas na auditoria)."""

    def post_login(self, username, password, ip="10.0.0.1"):
        return self.client.post(reverse("login"), {"username": username, "password": password}, REMOTE_ADDR=ip)

    def test_five_failures_lock_the_username_even_with_right_password(self):
        user = self.users[Role.SECRETARIA]
        for _ in range(5):
            self.post_login(user.username, "errada")
        resp = self.post_login(user.username, PW)
        self.assertContains(resp, "Muitas tentativas")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_lock_does_not_reveal_if_account_exists(self):
        for _ in range(5):
            self.post_login("nao-existe", "x")
        self.assertContains(self.post_login("nao-existe", "x"), "Muitas tentativas")

    def test_other_accounts_and_old_failures_are_not_affected(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.core.models import AuditLog

        user = self.users[Role.SECRETARIA]
        for _ in range(5):
            self.post_login(user.username, "errada", ip="10.0.0.9")
        # Outra conta, outro computador: entra normalmente.
        resp = self.post_login(self.users[Role.DIRECAO].username, PW, ip="10.0.0.2")
        self.assertEqual(resp.status_code, 302)
        # Passada a janela de 15 minutos, a conta volta a entrar.
        AuditLog.objects.filter(action="login_failed").update(created_at=timezone.now() - timedelta(minutes=16))
        self.client.logout()
        self.assertEqual(self.post_login(user.username, PW, ip="10.0.0.9").status_code, 302)

    def test_new_password_from_school_unlocks_the_account(self):
        """A família errou 5 vezes, ligou na secretaria e recebeu uma senha
        nova: tem de conseguir entrar já, não daqui a 15 minutos."""
        resp_user = self.users[Role.RESPONSAVEL]
        for _ in range(5):
            self.post_login(resp_user.username, "errada", ip="10.0.0.5")
        self.login(self.users[Role.SECRETARIA])
        page = self.client.post(reverse("password_reset_user", args=[resp_user.pk]))
        temp = page.context["temp_password"]
        self.client.logout()
        self.assertEqual(self.post_login(resp_user.username, temp, ip="10.0.0.5").status_code, 302)

    def test_many_failures_from_one_address_lock_that_address(self):
        for i in range(20):
            self.post_login(f"conta{i}", "x", ip="10.0.0.66")
        resp = self.post_login(self.users[Role.DIRECAO].username, PW, ip="10.0.0.66")
        self.assertContains(resp, "Muitas tentativas")
        self.assertEqual(self.post_login(self.users[Role.DIRECAO].username, PW, ip="10.0.0.67").status_code, 302)


class SessionSettingsTests(SimpleTestCase):
    def test_session_is_short_and_ends_with_the_browser(self):
        self.assertLessEqual(settings.SESSION_COOKIE_AGE, 8 * 3600)
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)


class ErrorPagesTests(Round2Base):
    """Páginas de erro no visual da plataforma, em português e com saída."""

    def test_404_is_friendly(self):
        self.login(self.users[Role.SECRETARIA])
        resp = self.client.get("/nao-existe-esta-pagina/")
        self.assertEqual(resp.status_code, 404)
        self.assertContains(resp, "Não encontramos esta página", status_code=404)
        self.assertContains(resp, 'class="sidebar', status_code=404)  # com o menu da pessoa

    def test_403_shows_reason_and_way_out(self):
        self.login(self.users[Role.RESPONSAVEL])
        resp = self.client.get(reverse("analytics:student_dashboard", args=[self.bia.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, "não está disponível para você", status_code=403)
        self.assertContains(resp, reverse("home"), status_code=403)

    def test_expired_form_page(self):
        from django.test import Client

        c = Client(enforce_csrf_checks=True)
        resp = c.post(reverse("login"), {"username": "x", "password": "y"})
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, "O formulário expirou", status_code=403)

    def test_500_template_renders_without_request(self):
        from django.template.loader import render_to_string

        html = render_to_string("500.html")
        self.assertIn("Algo deu errado", html)


class FamilyGradesListTests(Round2Base):
    def setUp(self):
        super().setUp()
        from decimal import Decimal

        from apps.pedagogy.models import Grade

        self.ev = Evaluation.objects.create(school=self.school, subject=self.mat, class_group=self.turma,
                                            title="Prova", date=date(2026, 3, 10), created_by=self.prof,
                                            status=Evaluation.Status.PUBLISHED)
        Grade.objects.create(school=self.school, evaluation=self.ev, student=self.ana, value=Decimal("4.5"))
        Grade.objects.create(school=self.school, evaluation=self.ev, student=self.bia, value=Decimal("9.5"))

    def test_family_sees_own_grade_not_class_average(self):
        self.login(self.users[Role.RESPONSAVEL])
        resp = self.client.get(reverse("pedagogy:evaluation_list"))
        row = resp.context["rows"][0]
        self.assertIsNone(row["avg"])
        self.assertEqual([g.student for g in row["own"]], [self.ana])
        self.assertContains(resp, ">4,50<")
        self.assertNotContains(resp, "7,00")          # média da turma (4,5 e 9,5)
        self.assertNotContains(resp, "Média da turma")

    def test_staff_still_sees_class_average(self):
        self.login(self.users[Role.COORDENACAO])
        row = self.client.get(reverse("pedagogy:evaluation_list")).context["rows"][0]
        self.assertEqual(float(row["avg"]), 7.0)

    def test_family_cannot_filter_by_someone_elses_child(self):
        self.login(self.users[Role.RESPONSAVEL])
        url = reverse("pedagogy:evaluation_list")
        self.assertEqual(self.client.get(url + f"?estudante={self.bia.pk}").status_code, 403)
        self.assertEqual(self.client.get(url + f"?estudante={self.ana.pk}").status_code, 200)


class HomeTodayTests(Round2Base):
    def test_teacher_home_shows_todays_attendance_per_class(self):
        from django.utils import timezone

        from apps.pedagogy.models import AttendanceRecord

        self.login(self.prof)
        ws = self.client.get(reverse("home")).context["ws"]
        self.assertEqual(len(ws["classes"]), 1)            # uma linha por turma, não por disciplina
        self.assertEqual(ws["attendance_pending"], 1)
        AttendanceRecord.objects.create(school=self.school, class_group=self.turma, student=self.ana,
                                        date=timezone.localdate(), status="presente", recorded_by=self.prof)
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.context["ws"]["attendance_pending"], 0)
        if resp.context["ws"]["school_day"]:
            self.assertContains(resp, "Chamada feita")

    def test_secretaria_home_counts_open_requests(self):
        from apps.communication.models import ServiceRequest

        ServiceRequest.objects.create(school=self.school, requester=self.users[Role.RESPONSAVEL],
                                      title="Declaração", category="documento", description="Preciso")
        self.login(self.users[Role.SECRETARIA])
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.context["ws"]["requests_open"], 1)
        self.assertContains(resp, "Solicitações em aberto")


class NewNotificationsTests(Round2Base):
    def test_family_is_notified_of_a_new_occurrence(self):
        self.login(self.prof)
        self.client.post(reverse("pedagogy:occurrence_create"), {
            "student": self.ana.pk, "date": "2026-04-01", "description": "Chegou atrasada sem aviso.",
            "status": "aberta",
        })
        occ = Occurrence.objects.get(student=self.ana)
        n = Notification.objects.get(user=self.users[Role.RESPONSAVEL], kind="ocorrencia")
        self.assertEqual(n.url, reverse("pedagogy:occurrence_detail", args=[occ.pk]))
        # O responsável consegue abrir o que o aviso aponta.
        self.login(self.users[Role.RESPONSAVEL])
        self.assertEqual(self.client.get(n.url).status_code, 200)

    def test_guardian_is_notified_when_link_is_approved_or_rejected(self):
        novo = User.objects.create_user(username="pai", password=PW, role=Role.RESPONSAVEL, school=self.school)
        pedido = GuardianLink.objects.create(school=self.school, guardian=novo, student=self.bia, status="pendente")
        outro = GuardianLink.objects.create(school=self.school, guardian=novo, student=self.ana, status="pendente")
        self.login(self.users[Role.SECRETARIA])
        self.client.post(reverse("link_approve", args=[pedido.pk]))
        self.client.post(reverse("link_reject", args=[outro.pk]), {"reason": "Documento ilegível"})
        titles = list(Notification.objects.filter(user=novo, kind="vinculo").values_list("title", "body"))
        self.assertEqual(len(titles), 2)
        self.assertTrue(any("aprovado" in t for t, _ in titles))
        self.assertTrue(any("Documento ilegível" in b for _, b in titles))


class SetupStepsTests(TestCase):
    def test_new_school_sees_first_steps_with_links(self):
        school = School.objects.create(name="Nova", code="nova")
        sec = User.objects.create_user(username="sec", password=PW, role=Role.SECRETARIA, school=school)
        self.client.login(username="sec", password=PW)
        ws = self.client.get(reverse("home")).context["ws"]
        self.assertEqual(ws["setup_done"], 0)
        labels = {s["label"]: s for s in ws["setup"]}
        self.assertEqual(labels["Ano letivo"]["url"], reverse("school_year_create"))
        self.assertIsNone(labels["Contas dos professores"]["url"])   # só a administração cria
        for s in ws["setup"]:
            if s["url"]:
                self.assertEqual(self.client.get(s["url"]).status_code, 200, s["label"])
        self.assertTrue(sec)


class SetupStepsDoneTests(Round2Base):
    def test_checklist_disappears_when_everything_exists(self):
        from apps.pedagogy.models import AcademicRule

        self.login(self.users[Role.SECRETARIA])
        ws = self.client.get(reverse("home")).context["ws"]
        self.assertEqual([s["label"] for s in ws["setup"] if not s["done"]], ["Regras de média"])
        AcademicRule.objects.create(school=self.school, subject=self.mat, formula="aritmetica")
        self.assertEqual(self.client.get(reverse("home")).context["ws"]["setup"], [])


class StudentHomeTests(Round2Base):
    def test_student_home_shows_own_recent_grades_and_attendance(self):
        from decimal import Decimal

        from apps.pedagogy.models import AttendanceRecord, Grade

        conta = self.users[Role.ESTUDANTE]
        self.ana.user = conta
        self.ana.save(update_fields=["user"])
        ev = Evaluation.objects.create(school=self.school, subject=self.mat, class_group=self.turma, title="P1",
                                       date=date(2026, 3, 10), created_by=self.prof, status=Evaluation.Status.PUBLISHED)
        rascunho = Evaluation.objects.create(school=self.school, subject=self.mat, class_group=self.turma, title="P2",
                                             date=date(2026, 3, 20), created_by=self.prof)
        Grade.objects.create(school=self.school, evaluation=ev, student=self.ana, value=Decimal("8"))
        Grade.objects.create(school=self.school, evaluation=rascunho, student=self.ana, value=Decimal("2"))
        Grade.objects.create(school=self.school, evaluation=ev, student=self.bia, value=Decimal("5"))
        AttendanceRecord.objects.create(school=self.school, class_group=self.turma, student=self.ana,
                                        date=date(2026, 3, 10), status="falta", recorded_by=self.prof)
        self.login(conta)
        ws = self.client.get(reverse("home")).context["ws"]
        self.assertEqual([(g.evaluation.title, g.value) for g in ws["recent_grades"]], [("P1", Decimal("8"))])
        self.assertEqual(ws["attendance"]["absent"], 1)


class GradeEntrySafetyTests(Round2Base):
    """Nota digitada errado não apaga a anterior nem passa da escala."""

    def setUp(self):
        super().setUp()
        from decimal import Decimal

        from apps.pedagogy.models import Activity, Submission

        self.act = Activity.objects.create(
            school=self.school, class_group=self.turma, subject=self.mat, title="Lista 1",
            description="Fazer", status=Activity.Status.PUBLISHED, created_by=self.prof,
            published_date=date(2026, 3, 1), deadline=date(2026, 3, 5),
        )
        Submission.objects.create(school=self.school, activity=self.act, student=self.ana,
                                  status="entregue", grade=Decimal("8.50"))

    def test_invalid_grade_keeps_previous_and_warns(self):
        from apps.pedagogy.models import Submission

        self.login(self.prof)
        resp = self.client.post(reverse("pedagogy:activity_submissions", args=[self.act.pk]),
                                {f"status_{self.ana.pk}": "entregue", f"nota_{self.ana.pk}": "8,5a"}, follow=True)
        self.assertEqual(Submission.objects.get(student=self.ana).grade, 8.5)
        self.assertContains(resp, "Nota não aceita para Ana")

    def test_grade_above_scale_is_refused(self):
        from apps.pedagogy.models import Submission

        self.login(self.prof)
        self.client.post(reverse("pedagogy:activity_submissions", args=[self.act.pk]),
                         {f"status_{self.ana.pk}": "entregue", f"nota_{self.ana.pk}": "85"})
        self.assertEqual(Submission.objects.get(student=self.ana).grade, 8.5)   # 85 recusado na escala 0–10

    def test_blank_grade_clears_on_purpose(self):
        from apps.pedagogy.models import Submission

        self.login(self.prof)
        self.client.post(reverse("pedagogy:activity_submissions", args=[self.act.pk]),
                         {f"status_{self.ana.pk}": "entregue", f"nota_{self.ana.pk}": ""})
        self.assertIsNone(Submission.objects.get(student=self.ana).grade)

    def test_evaluation_grade_scale_follows_rule(self):
        from apps.pedagogy.models import AcademicRule, Grade

        ev = Evaluation.objects.create(school=self.school, subject=self.mat, class_group=self.turma, title="P1",
                                       date=date(2026, 3, 10), created_by=self.prof)
        self.login(self.prof)
        url = reverse("pedagogy:evaluation_grade", args=[ev.pk])
        self.client.post(url, {f"grade_{self.ana.pk}": "85"})
        self.assertFalse(Grade.objects.filter(evaluation=ev).exists())
        AcademicRule.objects.create(school=self.school, subject=self.mat, formula="aritmetica", passing_grade=60)
        self.client.post(url, {f"grade_{self.ana.pk}": "85"})
        self.assertEqual(Grade.objects.get(evaluation=ev).value, 85)
