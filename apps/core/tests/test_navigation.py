"""Navegação por perfil: todo item mostrado abre, e nada indevido aparece.

O §7.1 do Prompt 12 exige "todos os itens devem funcionar". Este teste abre,
como cada perfil, cada link do menu lateral e cada ação rápida: um item que
respondesse 403 (link para tela sem permissão) ou 500 falha aqui.
"""

from django.test import TestCase
from django.urls import reverse

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.core import navigation
from apps.core.models import Role, School, User
from apps.registry.models import Enrollment, GuardianLink, Student

PW = "senha-forte-1"


class NavigationBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        year = SchoolYear.objects.create(school=self.school, name="2026")
        self.turma = ClassGroup.objects.create(school=self.school, school_year=year, name="5º A")
        mat = Subject.objects.create(school=self.school, name="Matemática")
        self.users = {}
        for role in Role:
            self.users[role.value] = User.objects.create_user(
                username=f"u_{role.value}", password=PW, role=role.value, school=self.school,
                first_name=role.label,
            )
        TeacherAssignment.objects.create(
            school=self.school, school_year=year, teacher=self.users[Role.PROFESSOR.value],
            class_group=self.turma, subject=mat,
        )
        self.ana = Student.objects.create(school=self.school, first_name="Ana", last_name="Lima")
        self.ana.user = self.users[Role.ESTUDANTE.value]
        self.ana.save(update_fields=["user"])
        Enrollment.objects.create(
            school=self.school, student=self.ana, class_group=self.turma, school_year=year
        )
        GuardianLink.objects.create(
            school=self.school, guardian=self.users[Role.RESPONSAVEL.value],
            student=self.ana, status="aprovado",
        )

    def login(self, role):
        self.assertTrue(self.client.login(username=f"u_{role}", password=PW))
        return self.users[role]


class EveryItemOpensTests(NavigationBase):
    def test_every_menu_item_and_action_opens_for_each_role(self):
        for role in Role:
            with self.subTest(perfil=role.value):
                user = self.login(role.value)
                urls = navigation.all_visible_urls(user)
                self.assertTrue(urls, f"{role.value} sem nenhum item de menu")
                for url in urls:
                    resp = self.client.get(url)
                    self.assertEqual(
                        resp.status_code, 200, f"{role.value}: {url} respondeu {resp.status_code}"
                    )
                self.client.logout()

    def test_sidebar_renders_items_of_the_role(self):
        user = self.login(Role.PROFESSOR.value)
        resp = self.client.get(reverse("home"))
        for url in navigation.all_visible_urls(user):
            self.assertContains(resp, f'href="{url}"')


class NoUndueItemTests(NavigationBase):
    def _urls(self, role):
        return navigation.all_visible_urls(self.users[role])

    def test_only_admin_sees_user_management(self):
        alvo = reverse("user_list")
        for role in Role:
            with self.subTest(perfil=role.value):
                self.assertEqual(alvo in self._urls(role.value), role.value == Role.ADMIN.value)

    def test_secretaria_and_admin_do_not_see_pedagogical_observations(self):
        """Observações pedagógicas ficam fora da secretaria e da administração."""
        alvo = reverse("pedagogy:observation_list")
        self.assertNotIn(alvo, self._urls(Role.SECRETARIA.value))
        self.assertNotIn(alvo, self._urls(Role.ADMIN.value))
        self.assertIn(alvo, self._urls(Role.COORDENACAO.value))

    def test_family_and_student_do_not_see_registry(self):
        for role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value):
            urls = self._urls(role)
            for nome in ("enrollment_list", "guardian_list", "class_group_list"):
                self.assertNotIn(reverse(nome), urls)

    def test_student_dashboard_link_on_every_page(self):
        """Antes, "Meu painel" só existia no menu da tela inicial."""
        self.login(Role.ESTUDANTE.value)
        alvo = reverse("analytics:student_dashboard", args=[self.ana.pk])
        resp = self.client.get(reverse("pedagogy:activity_list"))
        self.assertContains(resp, f'href="{alvo}"')

    def test_student_without_record_has_no_dashboard_link(self):
        sem_ficha = User.objects.create_user(
            username="sem", password=PW, role=Role.ESTUDANTE.value, school=self.school
        )
        nav = navigation.build(sem_ficha)
        self.assertNotIn("my_dashboard", [i["key"] for i in nav["flat"]])


class ActiveAndBreadcrumbTests(NavigationBase):
    def test_child_page_marks_parent_item_active(self):
        self.login(Role.PROFESSOR.value)
        resp = self.client.get(reverse("pedagogy:activity_create"))
        nav = resp.context["nav"]
        self.assertEqual(nav["active"]["key"], "activities")
        self.assertEqual([c["label"] for c in nav["crumbs"]], ["Sala de aula", "Atividades de casa"])
        self.assertContains(resp, 'aria-current="page"')

    def test_home_only_active_on_home(self):
        self.login(Role.PROFESSOR.value)
        nav = self.client.get(reverse("pedagogy:attendance_list")).context["nav"]
        self.assertEqual(nav["active"]["key"], "attendance")
