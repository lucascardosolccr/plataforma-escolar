"""Coordenação pedagógica com designação (Prompt 14, rodada 7).

Aqui a designação automática dos testes antigos fica desligada: cada teste
define o que o coordenador acompanha.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.coordination.models import CoordinationRecord, CoordinatorAssignment
from apps.core.models import AuditLog, Role, School, User
from apps.pedagogy.models import Activity, Evaluation, Occurrence
from apps.registry.models import Enrollment, Student

PW = "Senha-forte-123"


class CoordBase(TestCase):
    coordenacao_restrita = True

    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        year = SchoolYear.objects.create(school=self.school, name="2026", is_current=True)
        self.a = ClassGroup.objects.create(school=self.school, school_year=year, name="7º A")
        self.b = ClassGroup.objects.create(school=self.school, school_year=year, name="7º B")
        self.mat = Subject.objects.create(school=self.school, name="Matemática")
        mk = lambda u, r: User.objects.create_user(u, password=PW, role=r, school=self.school, first_name=u.title())
        self.coord = mk("coord", Role.COORDENACAO)
        self.dir = mk("dir", Role.DIRECAO)
        self.prof_b = mk("profb", Role.PROFESSOR)
        TeacherAssignment.objects.create(school=self.school, school_year=year, teacher=self.prof_b,
                                         class_group=self.b, subject=self.mat)
        self.ana = Student.objects.create(school=self.school, first_name="Ana")
        self.bia = Student.objects.create(school=self.school, first_name="Bia")
        Enrollment.objects.create(school=self.school, student=self.ana, class_group=self.a, school_year=year)
        Enrollment.objects.create(school=self.school, student=self.bia, class_group=self.b, school_year=year)
        d = timezone.localdate() - timedelta(days=1)
        self.act_b = Activity.objects.create(school=self.school, class_group=self.b, subject=self.mat,
                                             title="Lista de equações", created_by=self.prof_b,
                                             status="publicada", published_date=d)
        Evaluation.objects.create(school=self.school, subject=self.mat, class_group=self.b, title="Prova B",
                                  date=d, created_by=self.prof_b)
        Occurrence.objects.create(school=self.school, student=self.bia, recorded_by=self.dir,
                                  description="Ocorrência da Bia", date=d)

    def login(self, user):
        self.client.logout()
        self.client.login(username=user.username, password=PW)

    def designate(self, **kw):
        d = CoordinatorAssignment.objects.create(school=self.school, coordinator=self.coord,
                                                 starts_on=timezone.localdate(), all_school=kw.pop("all_school", False))
        for c in kw.get("classes", []):
            d.class_groups.add(c)
        for t in kw.get("teachers", []):
            d.teachers.add(t)
        return d


class DesignationScopeTests(CoordBase):
    def test_without_designation_sees_no_student_data(self):
        self.login(self.coord)
        page = self.client.get(reverse("coordination:panel"))
        self.assertContains(page, "ainda não tem designação")
        self.assertEqual(self.client.get(reverse("student_detail", args=[self.ana.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("pedagogy:occurrence_list")), "Ocorrência da Bia")

    def test_class_designation_limits_everything(self):
        self.designate(classes=[self.a])
        self.login(self.coord)
        self.assertEqual(self.client.get(reverse("student_detail", args=[self.ana.pk])).status_code, 200)
        for url in (reverse("student_detail", args=[self.bia.pk]),
                    reverse("analytics:student_dashboard", args=[self.bia.pk]),
                    reverse("analytics:class_dashboard", args=[self.b.pk]),
                    reverse("pedagogy:activity_detail", args=[self.act_b.pk]),
                    reverse("pedagogy:occurrence_list") + f"?estudante={self.bia.pk}",
                    reverse("analytics:institutional_dashboard")):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertNotContains(self.client.get(reverse("student_list")), "Bia")
        self.assertNotContains(self.client.get(reverse("pedagogy:evaluation_list")), "Prova B")
        self.assertNotContains(self.client.get(reverse("pedagogy:activity_list")), "Lista de equações")
        self.assertNotContains(self.client.get(reverse("pedagogy:occurrence_list")), "Ocorrência da Bia")

    def test_teacher_designation_reaches_that_teachers_classes(self):
        self.designate(teachers=[self.prof_b])
        self.login(self.coord)
        self.assertEqual(self.client.get(reverse("analytics:class_dashboard", args=[self.b.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("student_detail", args=[self.ana.pk])).status_code, 403)

    def test_all_school_and_expired_designation(self):
        d = self.designate(all_school=True)
        self.login(self.coord)
        self.assertEqual(self.client.get(reverse("analytics:institutional_dashboard")).status_code, 200)
        d.ends_on = timezone.localdate() - timedelta(days=1)
        d.starts_on = timezone.localdate() - timedelta(days=30)
        d.save()
        self.login(self.coord)
        self.assertEqual(self.client.get(reverse("student_detail", args=[self.ana.pk])).status_code, 403)


class DesignationManagementTests(CoordBase):
    def test_only_direction_and_admin_designate(self):
        self.login(self.coord)
        self.assertEqual(self.client.get(reverse("coordination:designations")).status_code, 403)
        self.login(self.dir)
        resp = self.client.post(reverse("coordination:designations"), {
            "coordinator": self.coord.pk, "area": "Anos finais", "class_groups": [self.a.pk],
            "starts_on": timezone.localdate().isoformat()})
        self.assertEqual(resp.status_code, 302)
        d = CoordinatorAssignment.objects.get()
        self.assertEqual(list(d.class_groups.all()), [self.a])
        self.assertTrue(AuditLog.objects.filter(target_type="CoordinatorAssignment").exists())

    def test_empty_designation_refused(self):
        self.login(self.dir)
        resp = self.client.post(reverse("coordination:designations"), {
            "coordinator": self.coord.pk, "starts_on": timezone.localdate().isoformat()})
        self.assertContains(resp, "escola toda")
        self.assertFalse(CoordinatorAssignment.objects.exists())


class PanelAndRecordsTests(CoordBase):
    def test_panel_shows_only_scoped_classes_and_records(self):
        self.designate(classes=[self.a])
        self.login(self.coord)
        page = self.client.get(reverse("coordination:panel"))
        self.assertContains(page, "7º A")
        self.assertNotContains(page, "7º B")
        self.client.post(reverse("coordination:records"), {
            "kind": "orientacao", "date": timezone.localdate().isoformat(), "title": "Planejamento de frações",
            "notes": "Sugerida sequência com material concreto.", "class_group": self.a.pk})
        self.assertTrue(CoordinationRecord.objects.filter(title="Planejamento de frações").exists())
        # Turma fora do alcance é recusada (nem aparece como opção).
        resp = self.client.post(reverse("coordination:records"), {
            "kind": "reuniao", "date": timezone.localdate().isoformat(), "title": "Fora", "notes": "x",
            "class_group": self.b.pk})
        self.assertFalse(CoordinationRecord.objects.filter(title="Fora").exists())
        self.assertEqual(resp.status_code, 200)

    def test_family_and_teacher_cannot_open_panel(self):
        fam = User.objects.create_user("fam", password=PW, role=Role.RESPONSAVEL, school=self.school)
        for u in (fam, self.prof_b):
            self.login(u)
            self.assertEqual(self.client.get(reverse("coordination:panel")).status_code, 403)
            self.assertEqual(self.client.get(reverse("coordination:records")).status_code, 403)


class MigrationTests(TestCase):
    def test_existing_coordinators_keep_school_wide_access(self):
        import importlib

        from django.apps import apps as django_apps

        mod = importlib.import_module("apps.coordination.migrations.0002_designacao_inicial")
        school = School.objects.create(name="E", code="x")
        CoordinatorAssignment.objects.all().delete()
        u = User.objects.create_user("antiga", password=PW, role=Role.COORDENACAO, school=school)
        CoordinatorAssignment.objects.filter(coordinator=u).delete()
        mod.forwards(django_apps, None)
        self.assertTrue(CoordinatorAssignment.objects.get(coordinator=u).all_school)
        mod.backwards(django_apps, None)
        self.assertFalse(CoordinatorAssignment.objects.filter(coordinator=u).exists())
