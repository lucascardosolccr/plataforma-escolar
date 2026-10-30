"""Professor vê só as disciplinas atribuídas; permissões adicionais (Prompt 14, rodada 6).

Os testes tentam pela URL e por parâmetros, não só pela interface.
"""

from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment, TeacherPermission
from apps.academics.permissions import teacher_pairs
from apps.core.models import AuditLog, Role, School, User
from apps.pedagogy.models import Activity, Evaluation, Grade, PedagogicalObservation
from apps.registry.models import Enrollment, Student

PW = "Senha-forte-123"


class PermBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        self.year = SchoolYear.objects.create(school=self.school, name="2026", is_current=True)
        self.turma = ClassGroup.objects.create(school=self.school, school_year=self.year, name="6º A")
        self.mat = Subject.objects.create(school=self.school, name="Matemática")
        self.port = Subject.objects.create(school=self.school, name="Português")
        mk = lambda u, r: User.objects.create_user(u, password=PW, role=r, school=self.school, first_name=u.title())
        self.prof = mk("prof", Role.PROFESSOR)
        self.colega = mk("colega", Role.PROFESSOR)
        self.dir = mk("dir", Role.DIRECAO)
        self.sec = mk("sec", Role.SECRETARIA)
        self.coord = mk("coord", Role.COORDENACAO)
        TeacherAssignment.objects.create(school=self.school, school_year=self.year, teacher=self.prof,
                                         class_group=self.turma, subject=self.mat)
        TeacherAssignment.objects.create(school=self.school, school_year=self.year, teacher=self.colega,
                                         class_group=self.turma, subject=self.port)
        self.ana = Student.objects.create(school=self.school, first_name="Ana")
        Enrollment.objects.create(school=self.school, student=self.ana, class_group=self.turma, school_year=self.year)
        d = timezone.localdate() - timedelta(days=1)
        self.ev_mat = Evaluation.objects.create(school=self.school, subject=self.mat, class_group=self.turma,
                                                title="Prova de frações", date=d, created_by=self.prof,
                                                status="publicada")
        self.ev_port = Evaluation.objects.create(school=self.school, subject=self.port, class_group=self.turma,
                                                 title="Redação narrativa", date=d, created_by=self.colega,
                                                 status="publicada")
        Grade.objects.create(school=self.school, evaluation=self.ev_mat, student=self.ana, value=8)
        Grade.objects.create(school=self.school, evaluation=self.ev_port, student=self.ana, value=4)
        self.act_port = Activity.objects.create(school=self.school, class_group=self.turma, subject=self.port,
                                                title="Leitura do capítulo 3", created_by=self.colega,
                                                status="publicada", published_date=d)

    def login(self, user):
        self.client.logout()
        self.client.login(username=user.username, password=PW)


class SubjectRestrictionTests(PermBase):
    def test_lists_show_only_own_subjects(self):
        self.login(self.prof)
        ev = self.client.get(reverse("pedagogy:evaluation_list"))
        self.assertContains(ev, "Prova de frações")
        self.assertNotContains(ev, "Redação narrativa")
        self.assertNotContains(self.client.get(reverse("pedagogy:activity_list")), "Leitura do capítulo 3")

    def test_url_tampering_is_refused(self):
        self.login(self.prof)
        for url in (reverse("pedagogy:evaluation_grade", args=[self.ev_port.pk]),
                    reverse("pedagogy:evaluation_edit", args=[self.ev_port.pk]),
                    reverse("pedagogy:activity_detail", args=[self.act_port.pk]),
                    reverse("pedagogy:activity_edit", args=[self.act_port.pk]),
                    reverse("pedagogy:activity_submissions", args=[self.act_port.pk])):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        # POST forjado criando avaliação em disciplina alheia.
        resp = self.client.post(reverse("pedagogy:evaluation_create"), {
            "class_group": self.turma.pk, "subject": self.port.pk, "title": "Invasão", "kind": "prova",
            "weight": "1", "date": "2026-03-10"})
        self.assertFalse(Evaluation.objects.filter(title="Invasão").exists())
        self.assertEqual(resp.status_code, 200)

    def test_dashboards_and_report_hide_other_subjects(self):
        self.login(self.prof)
        page = self.client.get(reverse("analytics:student_dashboard", args=[self.ana.pk]) + "?periodo=tudo")
        self.assertEqual(page.status_code, 200)
        names = [s["subject"].name for s in page.context["report"]["academic"]["subjects"]]
        self.assertEqual(names, ["Matemática"])
        self.assertContains(page, "só as disciplinas que leciona")
        cls = self.client.get(reverse("analytics:class_dashboard", args=[self.turma.pk]) + "?periodo=tudo")
        self.assertEqual([s.name for s in cls.context["report"]["subjects"]], ["Matemática"])
        rep = self.client.get(reverse("analytics:report_detail", args=["boletim"]) + f"?student={self.ana.pk}")
        self.assertContains(rep, "Matemática")
        self.assertNotContains(rep, "Português")
        # A coordenação continua vendo tudo.
        self.login(self.coord)
        page = self.client.get(reverse("analytics:student_dashboard", args=[self.ana.pk]) + "?periodo=tudo")
        self.assertEqual(len(page.context["report"]["academic"]["subjects"]), 2)

    def test_observations_of_other_subjects_hidden(self):
        PedagogicalObservation.objects.create(school=self.school, student=self.ana, teacher=self.colega,
                                              subject=self.port, content="Interpretação de texto")
        PedagogicalObservation.objects.create(school=self.school, student=self.ana, teacher=self.colega,
                                              content="Observação geral da turma")
        self.login(self.prof)
        page = self.client.get(reverse("pedagogy:observation_list") + f"?estudante={self.ana.pk}")
        self.assertNotContains(page, "Interpretação de texto")
        self.assertContains(page, "Observação geral da turma")

    def test_assignment_period_is_respected(self):
        a = TeacherAssignment.objects.get(teacher=self.prof)
        a.ends_on = timezone.localdate() - timedelta(days=1)
        a.save()
        self.assertEqual(teacher_pairs(User.objects.get(pk=self.prof.pk)), set())
        self.login(self.prof)
        self.assertEqual(self.client.get(reverse("pedagogy:evaluation_grade", args=[self.ev_mat.pk])).status_code, 403)


class ExtraPermissionTests(PermBase):
    def grant(self, kind="consulta", **extra):
        self.login(self.dir)
        data = {"teacher": self.prof.pk, "class_group": self.turma.pk, "subject": self.port.pk, "kind": kind,
                "starts_on": timezone.localdate().isoformat(), "justification": "Substituição na licença"}
        data.update(extra)
        return self.client.post(reverse("teacher_permissions"), data)

    def test_view_permission_allows_reading_not_writing(self):
        self.grant("consulta")
        perm = TeacherPermission.objects.get()
        self.assertEqual(perm.granted_by, self.dir)
        self.assertTrue(AuditLog.objects.filter(target_type="TeacherPermission").exists())
        self.login(self.prof)
        self.assertContains(self.client.get(reverse("pedagogy:evaluation_list")), "Redação narrativa")
        self.assertEqual(self.client.get(reverse("pedagogy:activity_detail", args=[self.act_port.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("pedagogy:evaluation_grade", args=[self.ev_port.pk])).status_code, 403)

    def test_edit_permission_allows_grading_and_revoke_cuts_access(self):
        self.grant("edicao")
        self.login(self.prof)
        self.assertEqual(self.client.get(reverse("pedagogy:evaluation_grade", args=[self.ev_port.pk])).status_code, 200)
        self.login(self.sec)
        self.client.post(reverse("teacher_permission_revoke", args=[TeacherPermission.objects.get().pk]))
        perm = TeacherPermission.objects.get()
        self.assertEqual((perm.status, perm.revoked_by), ("revogada", self.sec))
        self.login(self.prof)
        self.assertEqual(self.client.get(reverse("pedagogy:evaluation_grade", args=[self.ev_port.pk])).status_code, 403)

    def test_expired_or_future_permission_gives_nothing(self):
        today = timezone.localdate()
        TeacherPermission.objects.create(school=self.school, teacher=self.prof, class_group=self.turma,
                                         subject=self.port, kind="edicao", starts_on=today - timedelta(days=10),
                                         ends_on=today - timedelta(days=1), justification="x")
        TeacherPermission.objects.create(school=self.school, teacher=self.prof, class_group=self.turma,
                                         subject=self.port, kind="edicao", starts_on=today + timedelta(days=5),
                                         justification="y")
        self.assertEqual(teacher_pairs(User.objects.get(pk=self.prof.pk)), {(self.turma.pk, self.mat.pk)})

    def test_only_granters_and_justification_required(self):
        for u in (self.prof, self.coord):
            self.login(u)
            self.assertEqual(self.client.get(reverse("teacher_permissions")).status_code, 403)
        resp = self.grant(justification="")
        self.assertFalse(TeacherPermission.objects.exists())
        self.assertContains(resp, "justificativa")
