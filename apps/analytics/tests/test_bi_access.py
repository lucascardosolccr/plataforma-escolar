"""Painéis de BI: quem abre o quê, inclusive pela exportação.

O Prompt 13 (§11) exige restrição no backend, não só na interface. Cada
painel e cada exportação é aberto por todos os perfis relevantes.
"""

import csv
import io
import zipfile
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.core.models import AuditLog, Role, School, User
from apps.pedagogy.models import Evaluation, Grade
from apps.registry.models import Enrollment, GuardianLink, Student

from ..metrics import METRICS

PW = "senha-forte-1"
Q = "?periodo=personalizado&inicio=2026-01-01&fim=2026-12-31"


class BIAccessBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        year = SchoolYear.objects.create(school=self.school, name="2026")
        self.t1 = ClassGroup.objects.create(school=self.school, school_year=year, name="5º A")
        self.t2 = ClassGroup.objects.create(school=self.school, school_year=year, name="5º B")
        self.mat = Subject.objects.create(school=self.school, name="Matemática")
        self.por = Subject.objects.create(school=self.school, name="Português")

        def mk(username, role):
            return User.objects.create_user(username=username, password=PW, role=role, school=self.school)

        self.users = {r: mk(r, r) for r in ("admin", "direcao", "coordenacao", "secretaria")}
        self.prof = mk("prof", Role.PROFESSOR)        # Matemática no 5º A
        self.prof_b = mk("prof_b", Role.PROFESSOR)    # Português no 5º B
        self.resp = mk("resp", Role.RESPONSAVEL)
        self.resp_x = mk("resp_x", Role.RESPONSAVEL)  # sem vínculo
        self.conta = mk("aluno", Role.ESTUDANTE)
        TeacherAssignment.objects.create(school=self.school, school_year=year, teacher=self.prof,
                                         class_group=self.t1, subject=self.mat)
        TeacherAssignment.objects.create(school=self.school, school_year=year, teacher=self.prof_b,
                                         class_group=self.t2, subject=self.por)
        self.ana = Student.objects.create(school=self.school, first_name="=CMD", last_name="Ana")
        self.ana.user = self.conta
        self.ana.save(update_fields=["user"])
        self.bia = Student.objects.create(school=self.school, first_name="Bia")
        for s, t in ((self.ana, self.t1), (self.bia, self.t2)):
            Enrollment.objects.create(school=self.school, student=s, class_group=t, school_year=year)
        GuardianLink.objects.create(school=self.school, guardian=self.resp, student=self.ana, status="aprovado")
        ev = Evaluation.objects.create(school=self.school, subject=self.mat, class_group=self.t1, title="P1",
                                       date=date(2026, 3, 10), status=Evaluation.Status.PUBLISHED, created_by=self.prof)
        Grade.objects.create(school=self.school, evaluation=ev, student=self.ana, value=Decimal("7"))

    def status(self, username, url):
        self.client.logout()
        self.assertTrue(self.client.login(username=username, password=PW))
        return self.client.get(url).status_code

    def matrix(self, url, allowed):
        everyone = list(self.users) + ["prof", "prof_b", "resp", "resp_x", "aluno"]
        for u in everyone:
            with self.subTest(usuario=u, url=url):
                self.assertEqual(self.status(u, url), 200 if u in allowed else 403)


class PanelAccessTests(BIAccessBase):
    def test_student_panel_and_exports(self):
        allowed = ["admin", "direcao", "coordenacao", "secretaria", "prof", "resp", "aluno"]
        self.matrix(reverse("analytics:student_dashboard", args=[self.ana.pk]) + Q, allowed)
        for fmt in ("csv", "xlsx"):
            self.matrix(reverse("analytics:student_export", args=[self.ana.pk, fmt]) + Q, allowed)

    def test_class_panel_and_export(self):
        allowed = ["admin", "direcao", "coordenacao", "secretaria", "prof"]
        self.matrix(reverse("analytics:class_dashboard", args=[self.t1.pk]) + Q, allowed)
        self.matrix(reverse("analytics:class_export", args=[self.t1.pk, "csv"]) + Q, allowed)

    def test_subject_panel_and_export(self):
        allowed = ["admin", "direcao", "coordenacao", "secretaria", "prof"]
        self.matrix(reverse("analytics:subject_dashboard", args=[self.mat.pk]) + Q, allowed)
        self.matrix(reverse("analytics:subject_export", args=[self.mat.pk, "csv"]) + Q, allowed)

    def test_teacher_cannot_force_other_class_in_subject(self):
        url = reverse("analytics:subject_dashboard", args=[self.mat.pk]) + f"{Q}&turma={self.t2.pk}"
        self.assertEqual(self.status("prof", url), 403)
        url = reverse("analytics:subject_dashboard", args=[self.por.pk]) + Q
        self.assertEqual(self.status("prof", url), 403)   # não leciona Português

    def test_subject_index_picks_an_allowed_subject(self):
        self.assertEqual(self.status("prof", reverse("analytics:subject_index")), 200)
        self.assertEqual(self.status("resp", reverse("analytics:subject_index")), 403)

    def test_teacher_panel_only_for_the_teacher_himself(self):
        self.matrix(reverse("analytics:teacher_dashboard") + Q, ["prof", "prof_b"])

    def test_data_quality_only_management(self):
        self.matrix(reverse("analytics:data_quality") + Q, ["admin", "direcao", "coordenacao", "secretaria"])

    def test_institutional_only_direction_coordination_admin(self):
        self.matrix(reverse("analytics:institutional_dashboard") + Q, ["admin", "direcao", "coordenacao"])

    def test_other_school_student_is_not_reachable(self):
        outra = School.objects.create(name="Outra", code="o")
        alheio = Student.objects.create(school=outra, first_name="Zé")
        self.assertEqual(self.status("secretaria", reverse("analytics:student_dashboard", args=[alheio.pk])), 403)


class PanelContentPrivacyTests(BIAccessBase):
    def test_family_and_student_do_not_see_class_comparison_or_quality(self):
        url = reverse("analytics:student_dashboard", args=[self.ana.pk]) + Q
        for u in ("resp", "aluno"):
            self.status(u, url)
            resp = self.client.get(url)
            self.assertFalse(resp.context["is_team"])
            self.assertFalse(resp.context["report"]["academic"]["class_comparison"])
            self.assertNotContains(resp, 'id="qualidade"')
        self.status("prof", url)
        self.assertContains(self.client.get(url), 'id="qualidade"')

    def test_matrix_row_links_to_student_panel(self):
        self.status("prof", "/")
        resp = self.client.get(reverse("analytics:class_dashboard", args=[self.t1.pk]) + Q)
        self.assertContains(resp, reverse("analytics:student_dashboard", args=[self.ana.pk]))

    def test_methodology_lists_every_metric(self):
        self.status("resp", "/")
        resp = self.client.get(reverse("analytics:methodology"))
        for key in METRICS:
            self.assertContains(resp, f'id="{key}"')


class ExportTests(BIAccessBase):
    def test_export_is_audited(self):
        self.status("resp", "/")
        self.client.get(reverse("analytics:student_export", args=[self.ana.pk, "csv"]) + Q)
        log = AuditLog.objects.get(action="export")
        self.assertEqual(log.user, self.resp)
        self.assertIn("Painel individual", log.detail)

    def test_xlsx_is_valid_and_neutralizes_formulas(self):
        self.status("secretaria", "/")
        resp = self.client.get(reverse("analytics:student_export", args=[self.ana.pk, "xlsx"]) + Q)
        self.assertEqual(resp["Content-Type"],
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        z = zipfile.ZipFile(io.BytesIO(resp.content))
        self.assertIsNone(z.testzip())
        workbook = z.read("xl/workbook.xml").decode()
        for aba in ("Sobre", "Resumo", "Disciplinas", "Avaliações", "Faltas", "Atividades"):
            self.assertIn(f'name="{aba}"', workbook)
        sobre = z.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn("'=CMD Ana", sobre)       # nome começando com "=" vira texto
        self.assertNotIn(">=CMD", sobre)

    def test_csv_has_context_header_and_blank_for_missing(self):
        self.status("secretaria", "/")
        resp = self.client.get(reverse("analytics:class_export", args=[self.t1.pk, "csv"]) + Q)
        texto = resp.content.decode("utf-8-sig")
        self.assertIn("Painel da turma", texto)
        self.assertIn("Período: 01/01/2026 a 31/12/2026", texto)
        self.assertIn("Ausência de dado aparece em branco", texto)

    def test_csv_never_starts_a_cell_with_a_formula(self):
        # O título de seção era "== Resumo ==" (o Excel lia como fórmula e mostrava erro) e o cabeçalho com o
        # nome do estudante não passava pela proteção contra fórmula.
        self.status("secretaria", "/")
        resp = self.client.get(reverse("analytics:student_export", args=[self.ana.pk, "csv"]) + Q)
        rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))
        self.assertIn(["[Resumo]"], rows)
        self.assertFalse([c for r in rows for c in r if c[:1] in ("=", "+", "@")])
        self.assertTrue(any(c.startswith("'=CMD Ana") for r in rows for c in r))

    def test_unknown_format_is_refused(self):
        self.status("secretaria", "/")
        resp = self.client.get(reverse("analytics:student_export", args=[self.ana.pk, "pdf"]) + Q)
        self.assertEqual(resp.status_code, 403)
