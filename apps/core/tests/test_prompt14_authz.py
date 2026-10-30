"""Matriz de autorização das telas do Prompt 14 (rodada 12).

Para cada tela nova, os perfis que abrem (200) e os que são recusados.
Também tenta abrir, pela URL, objetos de OUTRA escola.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment, TeacherPermission
from apps.coordination.models import CoordinationRecord
from apps.core.models import Role, School, User
from apps.pedagogy.models import Activity
from apps.printing.models import PrintRequest
from apps.registry.models import ImportBatch, Student, StudentApplication

PW = "Senha-forte-123"
ALL = set(Role.values)
MGMT3 = {Role.SECRETARIA, Role.DIRECAO, Role.ADMIN}

MATRIX = [
    ("student_import", {Role.SECRETARIA, Role.ADMIN}),
    ("student_import_template", {Role.SECRETARIA, Role.ADMIN}),
    ("student_photo_batch", {Role.SECRETARIA, Role.ADMIN}),
    ("application_review_list", {Role.SECRETARIA, Role.ADMIN}),
    ("registration_settings", MGMT3),
    ("family_applications", {Role.RESPONSAVEL}),
    ("photo_pending", MGMT3),
    ("my_photo", ALL),
    ("pending_center", ALL),
    ("school_calendar:official", MGMT3),
    ("rotina:menu", ALL),
    ("rotina:menu_edit", MGMT3),
    ("rotina:schedule_index", ALL),
    ("teacher_permissions", MGMT3),
    ("coordination:panel", {Role.COORDENACAO, Role.DIRECAO}),
    ("coordination:records", {Role.COORDENACAO, Role.DIRECAO}),
    ("coordination:designations", {Role.DIRECAO, Role.ADMIN}),
    ("printing:mine", {Role.PROFESSOR}),
    ("printing:queue", {Role.COORDENACAO, Role.DIRECAO, Role.SECRETARIA, Role.ADMIN}),
    ("communication:notification_rules", {Role.DIRECAO, Role.ADMIN}),
    ("communication:notification_preferences", ALL),
]


class AuthzBase(TestCase):
    def setUp(self):
        self.a = School.objects.create(name="Escola A", code="a")
        self.b = School.objects.create(name="Escola B", code="b")
        for school in (self.a, self.b):
            SchoolYear.objects.create(school=school, name="2026", is_current=True)
        self.users = {r: User.objects.create_user(f"a-{r}", password=PW, role=r, school=self.a) for r in Role.values}
        self.b_users = {r: User.objects.create_user(f"b-{r}", password=PW, role=r, school=self.b) for r in Role.values}
        Student.objects.create(school=self.a, first_name="Própria", user=self.users[Role.ESTUDANTE])
        Student.objects.create(school=self.b, first_name="Outra", user=self.b_users[Role.ESTUDANTE])

    def login(self, user):
        self.client.logout()
        self.client.login(username=user.username, password=PW)


class RoleMatrixTests(AuthzBase):
    def test_every_new_screen_by_role(self):
        for role, user in self.users.items():
            self.login(user)
            for name, allowed in MATRIX:
                code = self.client.get(reverse(name)).status_code
                with self.subTest(perfil=role, tela=name):
                    if role in allowed:
                        self.assertEqual(code, 200)
                    else:
                        self.assertIn(code, (302, 403, 404))


class CrossSchoolTests(AuthzBase):
    def test_objects_of_another_school_are_unreachable(self):
        year_b = SchoolYear.objects.get(school=self.b)
        cg_b = ClassGroup.objects.create(school=self.b, school_year=year_b, name="B1")
        subj_b = Subject.objects.create(school=self.b, name="Arte")
        prof_b = self.b_users[Role.PROFESSOR]
        TeacherAssignment.objects.create(school=self.b, school_year=year_b, teacher=prof_b, class_group=cg_b,
                                         subject=subj_b)
        act_b = Activity.objects.create(school=self.b, class_group=cg_b, subject=subj_b, title="Atividade B",
                                        created_by=prof_b, class_date=timezone.localdate())
        batch_b = ImportBatch.objects.create(school=self.b, filename="b.csv", rows="[]")
        app_b = StudentApplication.objects.create(school=self.b, guardian=self.b_users[Role.RESPONSAVEL],
                                                  status="enviado", first_name="Criança B")
        req_b = PrintRequest.objects.create(school=self.b, activity=act_b, requested_by=prof_b,
                                            application_date=timezone.localdate(),
                                            desired_date=timezone.localdate(), copies=10, status="enviada")
        perm_b = TeacherPermission.objects.create(school=self.b, teacher=prof_b, class_group=cg_b, subject=subj_b,
                                                  starts_on=timezone.localdate(), justification="x")
        urls = [
            reverse("student_import_detail", args=[batch_b.pk]),
            reverse("student_import_rejected", args=[batch_b.pk]),
            reverse("application_review", args=[app_b.pk]),
            reverse("application_photo", args=[app_b.pk]),
            reverse("printing:detail", args=[req_b.pk]),
            reverse("printing:file", args=[req_b.pk]),
            reverse("rotina:schedule_class", args=[cg_b.pk]),
            reverse("user_photo", args=[prof_b.pk]),
        ]
        posts = [
            reverse("printing:act", args=[req_b.pk]),
            reverse("teacher_permission_revoke", args=[perm_b.pk]),
            reverse("student_import_confirm", args=[batch_b.pk]),
        ]
        for role in (Role.SECRETARIA, Role.ADMIN, Role.DIRECAO, Role.COORDENACAO):
            self.login(self.users[role])
            for url in urls:
                with self.subTest(perfil=role, url=url):
                    self.assertIn(self.client.get(url).status_code, (403, 404))
            for url in posts:
                with self.subTest(perfil=role, post=url):
                    self.assertIn(self.client.post(url, {"action": "approve", "mode": "novos"}).status_code,
                                  (403, 404))
        req_b.refresh_from_db()
        perm_b.refresh_from_db()
        self.assertEqual((req_b.status, perm_b.status), ("enviada", "ativa"))

    def test_internal_records_never_reach_family(self):
        cg = ClassGroup.objects.create(school=self.a, school_year=SchoolYear.objects.get(school=self.a), name="A1")
        CoordinationRecord.objects.create(school=self.a, kind="orientacao", date=timezone.localdate(),
                                          title="Conversa interna", notes="Sigiloso", class_group=cg)
        self.login(self.users[Role.RESPONSAVEL])
        for name in ("coordination:records", "coordination:panel", "printing:queue"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)
