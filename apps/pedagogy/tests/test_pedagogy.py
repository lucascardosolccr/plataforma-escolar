import tempfile
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.core.models import AuditLog, Role, School
from apps.registry.models import Enrollment, GuardianLink, Student

from ..models import (
    AbsenceJustification,
    AcademicRule,
    Activity,
    ActivityAttachment,
    AttendanceRecord,
    Evaluation,
    Grade,
    InterventionPlan,
    Occurrence,
    PedagogicalObservation,
    PlanNote,
    Submission,
)

User = get_user_model()


class PedagogyBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola A", code="a")
        self.school_b = School.objects.create(name="Escola B", code="b")
        pw = "senha-forte-1"
        self.admin = User.objects.create_user(
            username="adm", password=pw, role=Role.ADMIN, school=self.school
        )
        self.sec = User.objects.create_user(
            username="sec", password=pw, role=Role.SECRETARIA, school=self.school
        )
        self.coord = User.objects.create_user(
            username="coord", password=pw, role=Role.COORDENACAO, school=self.school
        )
        self.direc = User.objects.create_user(
            username="dir", password=pw, role=Role.DIRECAO, school=self.school
        )
        self.prof = User.objects.create_user(
            username="prof", password=pw, role=Role.PROFESSOR, school=self.school
        )
        self.prof2 = User.objects.create_user(
            username="prof2", password=pw, role=Role.PROFESSOR, school=self.school
        )
        self.other_prof = User.objects.create_user(
            username="prof_b", password=pw, role=Role.PROFESSOR, school=self.school_b
        )
        self.resp = User.objects.create_user(
            username="resp", password=pw, role=Role.RESPONSAVEL, school=self.school
        )
        self.year = SchoolYear.objects.create(school=self.school, name="2026")
        self.turma = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="1º Ano A"
        )
        self.turma_b = ClassGroup.objects.create(
            school=self.school, school_year=self.year, name="1º Ano B"
        )
        self.mat = Subject.objects.create(school=self.school, name="Matemática")
        self.port = Subject.objects.create(school=self.school, name="Língua Portuguesa")
        TeacherAssignment.objects.create(
            school=self.school,
            school_year=self.year,
            teacher=self.prof,
            class_group=self.turma,
            subject=self.mat,
        )
        TeacherAssignment.objects.create(
            school=self.school,
            school_year=self.year,
            teacher=self.prof2,
            class_group=self.turma_b,
            subject=self.port,
        )
        self.ana = Student.objects.create(school=self.school, first_name="Ana")
        self.bea = Student.objects.create(school=self.school, first_name="Beatriz")
        Enrollment.objects.create(
            school=self.school, student=self.ana, class_group=self.turma, school_year=self.year
        )
        Enrollment.objects.create(
            school=self.school, student=self.bea, class_group=self.turma_b, school_year=self.year
        )
        GuardianLink.objects.create(
            school=self.school, guardian=self.resp, student=self.ana, status="aprovado"
        )

    def login(self, username):
        self.client.login(username=username, password="senha-forte-1")

    def make_evaluation(self, status="rascunho"):
        return Evaluation.objects.create(
            school=self.school,
            subject=self.mat,
            class_group=self.turma,
            title="Prova de Matemática",
            status=status,
            created_by=self.prof,
        )


class EvaluationTests(PedagogyBase):
    def test_professor_creates_evaluation_on_own_assignment(self):
        self.login("prof")
        resp = self.client.post(
            reverse("pedagogy:evaluation_create"),
            {
                "class_group": self.turma.pk,
                "subject": self.mat.pk,
                "title": "Prova bimestral",
                "weight": "2.00",
                "date": "2026-03-15",
                "status": "rascunho",
            },
            follow=True,
        )
        self.assertTrue(Evaluation.objects.filter(title="Prova bimestral").exists())
        self.assertNotContains(resp, "Falha")

    def test_professor_cannot_create_outside_assignment(self):
        self.login("prof")
        resp = self.client.post(
            reverse("pedagogy:evaluation_create"),
            {
                "class_group": self.turma_b.pk,
                "subject": self.port.pk,
                "title": "Prova invasiva",
            },
        )
        self.assertFalse(Evaluation.objects.filter(title="Prova invasiva").exists())
        self.assertEqual(resp.status_code, 200)

    def test_coord_cannot_create_evaluation(self):
        self.login("coord")
        self.assertEqual(self.client.get(reverse("pedagogy:evaluation_create")).status_code, 403)

    def test_grade_batch_and_audit(self):
        ev = self.make_evaluation()
        self.login("prof")
        resp = self.client.post(
            reverse("pedagogy:evaluation_grade", args=[ev.pk]),
            {"grade_%d" % self.ana.pk: "8.50", "observation_all": "Bom desenvolvimento"},
            follow=True,
        )
        grade = Grade.objects.get(evaluation=ev, student=self.ana)
        self.assertEqual(float(grade.value), 8.5)
        self.assertContains(resp, "8.50")
        self.assertTrue(
            AuditLog.objects.filter(target_type="Grade", action="create", detail__contains="Ana").exists()
        )

    def test_only_assigned_professor_can_enter_grades(self):
        ev = self.make_evaluation()
        self.login("prof2")
        self.assertEqual(self.client.get(reverse("pedagogy:evaluation_grade", args=[ev.pk])).status_code, 403)

    def test_publish_makes_grades_visible_to_responsavel(self):
        ev = self.make_evaluation(status="rascunho")
        Grade.objects.create(
            school=self.school, evaluation=ev, student=self.ana, value="8.50"
        )
        self.login("prof")
        self.client.post(reverse("pedagogy:evaluation_publish", args=[ev.pk]))
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:evaluation_list"))
        self.assertContains(resp, "Prova de Matemática")
        self.assertContains(resp, "8,50")

    def test_responsavel_does_not_see_draft(self):
        self.make_evaluation(status="rascunho")
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:evaluation_list"))
        self.assertNotContains(resp, "Prova de Matemática")

    def test_responsavel_sees_only_own_child_class(self):
        ev = self.make_evaluation(status="publicada")
        Grade.objects.create(school=self.school, evaluation=ev, student=self.ana, value="6.00")
        # Beatriz não é filha de resp
        ev2 = Evaluation.objects.create(
            school=self.school, subject=self.port, class_group=self.turma_b,
            title="Prova de Português", status="publicada", created_by=self.prof2,
        )
        Grade.objects.create(school=self.school, evaluation=ev2, student=self.bea, value="9.00")
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:evaluation_list"))
        self.assertContains(resp, "Prova de Matemática")
        self.assertNotContains(resp, "Prova de Português")

    def test_deleted_draft_leaves_audit(self):
        ev = self.make_evaluation()
        self.login("prof")
        self.client.post(
            reverse("pedagogy:evaluation_edit", args=[ev.pk]),
            {"_delete": "1", "title": ev.title, "date": "2026-03-15"},
        )
        self.assertFalse(Evaluation.objects.filter(pk=ev.pk).exists())
        self.assertTrue(
            AuditLog.objects.filter(target_type="Evaluation", action="delete").exists()
        )

    def test_published_evaluation_cannot_be_edited_or_deleted(self):
        ev = self.make_evaluation(status="publicada")
        self.login("prof")
        resp = self.client.post(
            reverse("pedagogy:evaluation_edit", args=[ev.pk]),
            {"_delete": "1", "title": "novo", "date": "2026-03-15"},
            follow=True,
        )
        self.assertTrue(Evaluation.objects.filter(pk=ev.pk).exists())
        ev.refresh_from_db()
        self.assertEqual(ev.title, "Prova de Matemática")


class ActivityTests(PedagogyBase):
    """Atividades de casa por turma: publicação, alcance e autorização."""

    def _payload(self, **extra):
        data = {
            "class_group": self.turma.pk,
            "subject": self.mat.pk,
            "title": "Trabalho de geometria",
            "description": "Resolver os exercícios 1 a 10 do caderno.",
            "published_date": "2026-03-01",
        }
        data.update(extra)
        return data

    def make_activity(self, **extra):
        defaults = dict(
            school=self.school,
            class_group=self.turma,
            subject=self.mat,
            title="Dever de casa cap. 2",
            description="Ler o capítulo 2 e responder.",
            created_by=self.prof,
            status=Activity.Status.PUBLISHED,
            published_date=date(2026, 3, 1),
        )
        defaults.update(extra)
        return Activity.objects.create(**defaults)

    # --- professor: criação, rascunho, publicação ---

    def test_create_activity_and_submissions(self):
        self.login("prof")
        self.client.post(
            reverse("pedagogy:activity_create"),
            self._payload(_publish="1"),
            follow=True,
        )
        act = Activity.objects.get(title="Trabalho de geometria")
        self.assertEqual(act.status, Activity.Status.PUBLISHED)
        resp = self.client.post(
            reverse("pedagogy:activity_submissions", args=[act.pk]),
            {"status_%d" % self.ana.pk: "entregue"},
            follow=True,
        )
        sub = Submission.objects.get(activity=act, student=self.ana)
        self.assertEqual(sub.status, "entregue")
        self.assertContains(resp, "Entregue")

    def test_saved_without_publish_becomes_draft(self):
        self.login("prof")
        self.client.post(reverse("pedagogy:activity_create"), self._payload())
        act = Activity.objects.get(title="Trabalho de geometria")
        self.assertEqual(act.status, Activity.Status.DRAFT)

    def test_draft_is_invisible_to_guardian(self):
        self.make_activity(title="Rascunho oculto", status=Activity.Status.DRAFT)
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:activity_list"))
        self.assertNotContains(resp, "Rascunho oculto")

    def test_publishing_draft_makes_it_visible(self):
        act = self.make_activity(title="Vira publica", status=Activity.Status.DRAFT)
        self.login("prof")
        self.client.post(
            reverse("pedagogy:activity_edit", args=[act.pk]),
            self._payload(title="Vira publica", _publish="1"),
        )
        act.refresh_from_db()
        self.assertEqual(act.status, Activity.Status.PUBLISHED)
        self.login("resp")
        self.assertContains(
            self.client.get(reverse("pedagogy:activity_list")), "Vira publica"
        )

    def test_scheduled_activity_hidden_until_publication_date(self):
        """Data de publicação futura não vaza a atividade antes da hora."""
        self.make_activity(
            title="Agendada para depois",
            published_date=timezone.localdate() + timedelta(days=5),
        )
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:activity_list"))
        self.assertNotContains(resp, "Agendada para depois")

    # --- distribuição automática para a turma ---

    def test_publication_reaches_every_active_student_of_class(self):
        extra = Student.objects.create(school=self.school, first_name="Carlos")
        Enrollment.objects.create(
            school=self.school, student=extra, class_group=self.turma,
            school_year=self.year,
        )
        act = self.make_activity()
        self.login("prof")
        resp = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        # Alcance derivado da turma: nada foi lançado aluno por aluno.
        self.assertContains(resp, "Alcança <strong>2</strong>", html=False)
        self.assertEqual(Submission.objects.filter(activity=act).count(), 0)
        # Os dois estudantes aparecem nominalmente na tela de entregas.
        entregas = self.client.get(
            reverse("pedagogy:activity_submissions", args=[act.pk])
        )
        self.assertContains(entregas, "Ana")
        self.assertContains(entregas, "Carlos")

    def test_student_enrolled_after_publication_still_sees_activity(self):
        act = self.make_activity(title="Publicada antes da matricula")
        novo = Student.objects.create(school=self.school, first_name="Daniel")
        Enrollment.objects.create(
            school=self.school, student=novo, class_group=self.turma,
            school_year=self.year,
        )
        guardian = User.objects.create_user(
            username="resp_novo", password="senha-forte-1",
            role=Role.RESPONSAVEL, school=self.school,
        )
        GuardianLink.objects.create(
            school=self.school, guardian=guardian, student=novo, status="aprovado"
        )
        self.login("resp_novo")
        self.assertContains(
            self.client.get(reverse("pedagogy:activity_list")),
            "Publicada antes da matricula",
        )
        self.assertTrue(act.is_visible_to_family)

    def test_transferred_student_keeps_activity_history(self):
        """Mudar o vínculo não pode apagar o que já foi atribuído."""
        self.make_activity(title="Historico preservado")
        Enrollment.objects.filter(student=self.ana, class_group=self.turma).update(
            status="transferido"
        )
        self.login("resp")
        self.assertContains(
            self.client.get(reverse("pedagogy:activity_list")),
            "Historico preservado",
        )

    def test_activity_appears_in_individual_student_record(self):
        self.make_activity(title="Consta na ficha")
        for username in ("coord", "prof", "resp"):
            self.login(username)
            resp = self.client.get(reverse("student_detail", args=[self.ana.pk]))
            self.assertContains(
                resp, "Consta na ficha", msg_prefix=f"perfil {username}"
            )

    def test_individual_record_omits_draft(self):
        self.make_activity(title="Rascunho na ficha", status=Activity.Status.DRAFT)
        self.login("coord")
        resp = self.client.get(reverse("student_detail", args=[self.ana.pk]))
        self.assertNotContains(resp, "Rascunho na ficha")

    def test_class_without_students_publishes_without_error(self):
        act = self.make_activity(class_group=self.turma_b, subject=self.port)
        Enrollment.objects.filter(class_group=self.turma_b).delete()
        self.login("coord")
        resp = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        self.assertEqual(resp.status_code, 200)

    # --- família ---

    def test_responsavel_sees_activities_of_child(self):
        self.make_activity()
        self.make_activity(
            class_group=self.turma_b, subject=self.port, title="Leitura em voz alta"
        )
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:activity_list"))
        self.assertContains(resp, "Dever de casa")
        self.assertNotContains(resp, "Leitura em voz alta")

    def test_guardian_with_two_children_sees_which_child_each_belongs_to(self):
        GuardianLink.objects.create(
            school=self.school, guardian=self.resp, student=self.bea, status="aprovado"
        )
        self.make_activity(title="Tarefa da Ana")
        self.make_activity(
            class_group=self.turma_b, subject=self.port, title="Tarefa da Beatriz"
        )
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:activity_list"))
        self.assertContains(resp, "Tarefa da Ana")
        self.assertContains(resp, "Tarefa da Beatriz")
        self.assertContains(resp, "Ana")
        self.assertContains(resp, "Beatriz")

    def test_guardian_cannot_filter_by_unrelated_student(self):
        self.make_activity()
        self.login("resp")
        resp = self.client.get(
            reverse("pedagogy:activity_list"), {"estudante": self.bea.pk}
        )
        self.assertEqual(resp.status_code, 403)

    def test_guardian_without_link_cannot_open_activity(self):
        act = self.make_activity()
        outro = User.objects.create_user(
            username="resp_sem_vinculo", password="senha-forte-1",
            role=Role.RESPONSAVEL, school=self.school,
        )
        self.client.login(username=outro.username, password="senha-forte-1")
        resp = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_guardian_cannot_open_draft_by_guessing_id(self):
        act = self.make_activity(status=Activity.Status.DRAFT)
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_deadline_states_are_shown_to_family(self):
        self.make_activity(
            title="Prazo vencido", deadline=timezone.localdate() - timedelta(days=3)
        )
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:activity_list"))
        self.assertContains(resp, "Prazo encerrado")

    def test_family_sees_empty_state_without_activities(self):
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:activity_list"))
        self.assertContains(resp, "Nenhuma atividade de casa")

    # --- autorização do professor ---

    def test_teacher_cannot_publish_for_unassigned_class(self):
        self.login("prof")
        resp = self.client.post(
            reverse("pedagogy:activity_create"),
            self._payload(class_group=self.turma_b.pk, _publish="1"),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Activity.objects.filter(class_group=self.turma_b).exists())

    def test_teacher_cannot_mix_class_and_subject_from_different_assignments(self):
        """Par turma+disciplina é validado junto, não campo a campo."""
        TeacherAssignment.objects.create(
            school=self.school, school_year=self.year, teacher=self.prof,
            class_group=self.turma_b, subject=self.port,
        )
        self.login("prof")
        resp = self.client.post(
            reverse("pedagogy:activity_create"),
            self._payload(subject=self.port.pk, _publish="1"),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "não tem atribuição")
        self.assertFalse(
            Activity.objects.filter(class_group=self.turma, subject=self.port).exists()
        )

    def test_other_teacher_cannot_edit_activity(self):
        act = self.make_activity()
        self.login("prof2")
        resp = self.client.get(reverse("pedagogy:activity_edit", args=[act.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_edit_updates_activity_for_whole_class(self):
        act = self.make_activity()
        self.login("prof")
        self.client.post(
            reverse("pedagogy:activity_edit", args=[act.pk]),
            self._payload(title="Dever revisado", description="Instruções novas."),
        )
        act.refresh_from_db()
        self.assertEqual(act.title, "Dever revisado")
        self.login("resp")
        self.assertContains(
            self.client.get(reverse("pedagogy:activity_list")), "Dever revisado"
        )

    # --- cancelamento preserva histórico ---

    def test_cancel_keeps_activity_and_submissions(self):
        act = self.make_activity()
        Submission.objects.create(
            school=self.school, activity=act, student=self.ana, status="entregue"
        )
        self.login("prof")
        self.client.post(
            reverse("pedagogy:activity_cancel", args=[act.pk]),
            {"cancel_reason": "Aula remarcada"},
        )
        act.refresh_from_db()
        self.assertEqual(act.status, Activity.Status.CANCELED)
        self.assertEqual(act.cancel_reason, "Aula remarcada")
        self.assertTrue(Activity.objects.filter(pk=act.pk).exists())
        self.assertEqual(Submission.objects.filter(activity=act).count(), 1)

    def test_canceled_activity_still_visible_to_family_as_canceled(self):
        act = self.make_activity(
            status=Activity.Status.CANCELED, cancel_reason="Conteúdo adiado"
        )
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:activity_list"))
        self.assertContains(resp, "Cancelada")
        self.assertContains(resp, "Conteúdo adiado")

    def test_cancel_requires_reason(self):
        act = self.make_activity()
        self.login("prof")
        resp = self.client.post(
            reverse("pedagogy:activity_cancel", args=[act.pk]), {"cancel_reason": ""}
        )
        self.assertEqual(resp.status_code, 200)
        act.refresh_from_db()
        self.assertEqual(act.status, Activity.Status.PUBLISHED)


class ActivityQueryBudgetTests(PedagogyBase):
    """O numero de consultas nao pode crescer com o volume de dados.

    Mede a mesma pagina com pouco e com muito dado. Se a diferenca crescer
    junto com as linhas, ha N+1 e a tela degrada na escola real, onde ha
    centenas de estudantes e atividades.
    """

    def _seed(self, n_students, n_activities):
        for i in range(n_students):
            student = Student.objects.create(
                school=self.school, first_name=f"Aluno{i}"
            )
            Enrollment.objects.create(
                school=self.school, student=student, class_group=self.turma,
                school_year=self.year,
            )
            GuardianLink.objects.create(
                school=self.school, guardian=self.resp, student=student,
                status="aprovado",
            )
        for i in range(n_activities):
            Activity.objects.create(
                school=self.school, class_group=self.turma, subject=self.mat,
                title=f"Atividade {i}", description="x", created_by=self.prof,
                status=Activity.Status.PUBLISHED, published_date=date(2026, 3, 1),
            )

    def _count(self, url):
        self.login("resp")
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return len(ctx)

    def test_family_list_query_count_is_flat(self):
        url = reverse("pedagogy:activity_list")
        self._seed(2, 2)
        small = self._count(url)
        self._seed(25, 25)
        large = self._count(url)
        self.assertLessEqual(
            large,
            small + 2,
            f"consultas subiram de {small} para {large} ao crescer o volume: "
            "indica N+1 na lista da familia",
        )

    def test_student_record_query_count_is_flat(self):
        url = reverse("student_detail", args=[self.ana.pk])
        self._seed(2, 2)
        small = self._count(url)
        self._seed(25, 25)
        large = self._count(url)
        self.assertLessEqual(
            large,
            small + 2,
            f"consultas subiram de {small} para {large}: indica N+1 na ficha",
        )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="escola-test-media-"))
class ActivityAttachmentTests(PedagogyBase):
    def _upload(self, name="apoio.pdf", content=b"%PDF-1.4 conteudo"):
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    def make_published(self):
        return Activity.objects.create(
            school=self.school, class_group=self.turma, subject=self.mat,
            title="Com anexo", description="Ver o material.", created_by=self.prof,
            status=Activity.Status.PUBLISHED, published_date=date(2026, 3, 1),
        )

    def test_teacher_uploads_attachment_and_guardian_downloads(self):
        self.login("prof")
        self.client.post(
            reverse("pedagogy:activity_create"),
            {
                "class_group": self.turma.pk,
                "subject": self.mat.pk,
                "title": "Com anexo",
                "description": "Ver o material.",
                "published_date": "2026-03-01",
                "attachments": self._upload(),
                "_publish": "1",
            },
        )
        att = ActivityAttachment.objects.get()
        self.assertEqual(att.original_name, "apoio.pdf")
        self.login("resp")
        resp = self.client.get(
            reverse(
                "pedagogy:activity_attachment", args=[att.activity_id, att.pk]
            )
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")

    def test_executable_attachment_is_rejected(self):
        self.login("prof")
        self.client.post(
            reverse("pedagogy:activity_create"),
            {
                "class_group": self.turma.pk,
                "subject": self.mat.pk,
                "title": "Com executavel",
                "description": "Tentativa.",
                "published_date": "2026-03-01",
                "attachments": SimpleUploadedFile(
                    "virus.exe", b"MZ", content_type="application/octet-stream"
                ),
                "_publish": "1",
            },
        )
        self.assertFalse(Activity.objects.filter(title="Com executavel").exists())
        self.assertEqual(ActivityAttachment.objects.count(), 0)

    def test_guardian_without_link_cannot_download_attachment(self):
        act = self.make_published()
        att = ActivityAttachment.objects.create(
            activity=act, file=self._upload(), original_name="apoio.pdf",
            size=10, uploaded_by=self.prof,
        )
        User.objects.create_user(
            username="resp_estranho", password="senha-forte-1",
            role=Role.RESPONSAVEL, school=self.school,
        )
        self.client.login(username="resp_estranho", password="senha-forte-1")
        resp = self.client.get(
            reverse("pedagogy:activity_attachment", args=[act.pk, att.pk])
        )
        self.assertEqual(resp.status_code, 403)

    def test_attachment_of_draft_is_not_downloadable_by_family(self):
        act = self.make_published()
        act.status = Activity.Status.DRAFT
        act.save(update_fields=["status"])
        att = ActivityAttachment.objects.create(
            activity=act, file=self._upload(), original_name="apoio.pdf",
            size=10, uploaded_by=self.prof,
        )
        self.login("resp")
        resp = self.client.get(
            reverse("pedagogy:activity_attachment", args=[act.pk, att.pk])
        )
        self.assertEqual(resp.status_code, 403)


class AttendanceTests(PedagogyBase):
    def test_batch_register_and_unique_per_day(self):
        self.login("prof")
        self.client.post(
            reverse("pedagogy:attendance_register", args=[self.turma.pk]),
            {"date": "2026-03-10", "status_%d" % self.ana.pk: "falta"},
            follow=True,
        )
        self.assertTrue(
            AttendanceRecord.objects.filter(
                class_group=self.turma, student=self.ana, date="2026-03-10", status="falta"
            ).exists()
        )
        # segundo registro substitui (unique constraint)
        self.client.post(
            reverse("pedagogy:attendance_register", args=[self.turma.pk]),
            {"date": "2026-03-10", "status_%d" % self.ana.pk: "presente"},
            follow=True,
        )
        self.assertEqual(
            AttendanceRecord.objects.filter(
                class_group=self.turma, student=self.ana, date="2026-03-10"
            ).count(),
            1,
        )

    def test_unassigned_professor_cannot_register(self):
        self.login("prof2")
        self.assertEqual(
            self.client.get(
                reverse("pedagogy:attendance_register", args=[self.turma.pk])
            ).status_code,
            403,
        )

    def test_responsavel_sees_only_child_in_class_grid(self):
        AttendanceRecord.objects.create(
            school=self.school, class_group=self.turma, student=self.ana,
            date="2026-03-10", status="falta", recorded_by=self.prof,
        )
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:attendance_class", args=[self.turma.pk]))
        self.assertContains(resp, "Ana")
        self.assertNotContains(resp, "Beatriz")

    def test_responsavel_blocked_from_other_class(self):
        self.login("resp")
        self.assertEqual(
            self.client.get(reverse("pedagogy:attendance_class", args=[self.turma_b.pk])).status_code,
            403,
        )


class OccurrenceTests(PedagogyBase):
    def test_professor_creates_occurrence_for_own_student(self):
        self.login("prof")
        self.client.post(
            reverse("pedagogy:occurrence_create"),
            {
                "student": self.ana.pk,
                "description": "Não entregou a atividade",
                "date": "2026-03-10",
            },
            follow=True,
        )
        occ = Occurrence.objects.get(student=self.ana)
        self.assertEqual(occ.recorded_by, self.prof)
        self.assertTrue(
            AuditLog.objects.filter(target_type="Occurrence", action="create").exists()
        )

    def test_professor_cannot_occurrence_student_outside_class(self):
        self.login("prof")
        resp = self.client.post(
            reverse("pedagogy:occurrence_create"),
            {
                "student": self.bea.pk,
                "description": "invasivo",
                "date": "2026-03-10",
            },
        )
        self.assertFalse(Occurrence.objects.filter(student=self.bea).exists())
        self.assertEqual(resp.status_code, 403)

    def test_coord_creates_and_updates_with_history(self):
        self.login("coord")
        self.client.post(
            reverse("pedagogy:occurrence_create"),
            {"student": self.bea.pk, "description": "Atraso recorrente", "date": "2026-03-10"},
            follow=True,
        )
        occ = Occurrence.objects.get(student=self.bea)
        resp = self.client.post(
            reverse("pedagogy:occurrence_detail", args=[occ.pk]),
            {"status": "em_acompanhamento", "providencias": "Conversa individual", "encaminhamento": "Orientação educacional"},
            follow=True,
        )
        occ.refresh_from_db()
        self.assertEqual(occ.status, "em_acompanhamento")
        self.assertTrue(
            AuditLog.objects.filter(target_type="Occurrence", action="update").exists()
        )

    def test_admin_cannot_create_occurrence_but_sees_list(self):
        self.login("adm")
        self.assertEqual(self.client.get(reverse("pedagogy:occurrence_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("pedagogy:occurrence_list")).status_code, 200)

    def test_responsavel_sees_occurences_of_child_only(self):
        Occurrence.objects.create(
            school=self.school, student=self.ana, description="Aviso da turma",
            recorded_by=self.prof, date="2026-03-10",
        )
        Occurrence.objects.create(
            school=self.school, student=self.bea, description="Outra turma",
            recorded_by=self.prof2, date="2026-03-10",
        )
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:occurrence_list"))
        self.assertContains(resp, "Aviso da turma")
        self.assertNotContains(resp, "Outra turma")


class ObservationTests(PedagogyBase):
    def test_professor_creates_observation_for_own_student(self):
        self.login("prof")
        self.client.post(
            reverse("pedagogy:observation_create"),
            {
                "student": self.ana.pk,
                "content": "Dificuldade em frações",
                "dificuldades": "Operações básicas",
                "estrategias": "Material concreto",
            },
            follow=True,
        )
        self.assertTrue(
            PedagogicalObservation.objects.filter(
                student=self.ana, teacher=self.prof, content="Dificuldade em frações"
            ).exists()
        )

    def test_admin_and_secretaria_have_no_observation_access(self):
        self.login("adm")
        self.assertEqual(self.client.get(reverse("pedagogy:observation_list")).status_code, 403)
        self.login("sec")
        self.assertEqual(self.client.get(reverse("pedagogy:observation_list")).status_code, 403)

    def test_responsavel_sees_own_child_observations(self):
        PedagogicalObservation.objects.create(
            school=self.school, student=self.ana, teacher=self.prof,
            content="Progresso em leitura",
        )
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:observation_list"))
        self.assertContains(resp, "Progresso em leitura")


class PlanTests(PedagogyBase):
    def test_only_coord_creates_plan(self):
        self.login("prof")
        self.assertEqual(self.client.get(reverse("pedagogy:plan_create")).status_code, 403)
        self.login("coord")
        resp = self.client.post(
            reverse("pedagogy:plan_create"),
            {"student": self.ana.pk, "title": "Plano de reforço", "description": "Apoio em matemática"},
            follow=True,
        )
        self.assertTrue(InterventionPlan.objects.filter(title="Plano de reforço").exists())

    def test_coord_adds_note_and_changes_status(self):
        plan = InterventionPlan.objects.create(
            school=self.school, student=self.ana, title="Plano",
            description="Objetivos", created_by=self.coord,
        )
        self.login("coord")
        self.client.post(
            reverse("pedagogy:plan_detail", args=[plan.pk]),
            {"_action": "add_note", "note": "Melhora nas avaliações"},
            follow=True,
        )
        self.assertEqual(plan.notes.count(), 1)
        self.client.post(
            reverse("pedagogy:plan_detail", args=[plan.pk]),
            {"_action": "set_status", "status": "concluido"},
            follow=True,
        )
        plan.refresh_from_db()
        self.assertEqual(plan.status, "concluido")

    def test_responsavel_can_view_child_plan(self):
        plan = InterventionPlan.objects.create(
            school=self.school, student=self.ana, title="Plano do filho",
            description="Objetivos", created_by=self.coord,
        )
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:plan_detail", args=[plan.pk]))
        self.assertContains(resp, "Plano do filho")


class JustificationTests(PedagogyBase):
    def test_responsavel_submits_justification_for_child(self):
        self.login("resp")
        self.client.post(
            reverse("pedagogy:justification_create"),
            {
                "student_id": self.ana.pk,
                "start_date": "2026-03-01",
                "end_date": "2026-03-02",
                "reason": "Consulta médica",
            },
            follow=True,
        )
        just = AbsenceJustification.objects.get(student=self.ana)
        self.assertEqual(just.status, "recebida")
        self.assertEqual(just.submitted_by, self.resp)
        self.assertFalse(AttendanceRecord.objects.filter(student=self.ana).exists())

    def test_responsavel_cannot_justify_other_student(self):
        self.login("resp")
        resp = self.client.post(
            reverse("pedagogy:justification_create"),
            {"student_id": self.bea.pk, "start_date": "2026-03-01",
             "end_date": "2026-03-02", "reason": "x"},
            follow=True,
        )
        self.assertFalse(AbsenceJustification.objects.filter(student=self.bea).exists())

    def test_secretaria_approves_without_changing_official_attendance(self):
        just = AbsenceJustification.objects.create(
            school=self.school, student=self.ana, start_date="2026-03-01",
            end_date="2026-03-02", reason="Consulta", submitted_by=self.resp,
        )
        AttendanceRecord.objects.create(
            school=self.school, class_group=self.turma, student=self.ana,
            date="2026-03-01", status="falta", recorded_by=self.prof,
        )
        self.login("sec")
        self.client.post(
            reverse("pedagogy:justification_resolve", args=[just.pk, "aprovar"]),
            {"note": "Documento apresentado"},
            follow=True,
        )
        just.refresh_from_db()
        self.assertEqual(just.status, "aprovada")
        rec = AttendanceRecord.objects.get(student=self.ana, date="2026-03-01")
        self.assertEqual(rec.status, "falta")

    def test_only_secretaria_resolves(self):
        just = AbsenceJustification.objects.create(
            school=self.school, student=self.ana, start_date="2026-03-01",
            end_date="2026-03-02", reason="Consulta", submitted_by=self.resp,
        )
        self.login("coord")
        resp = self.client.post(
            reverse("pedagogy:justification_resolve", args=[just.pk, "aprovar"])
        )
        self.assertEqual(resp.status_code, 403)
        just.refresh_from_db()
        self.assertEqual(just.status, "recebida")

    def test_secretaria_cannot_submit_justification(self):
        self.login("sec")
        self.assertEqual(self.client.get(reverse("pedagogy:justification_create")).status_code, 403)


class RulesAndConfigTests(PedagogyBase):
    def test_only_secretaria_and_admin_edit_config(self):
        self.login("prof")
        self.assertEqual(self.client.get(reverse("pedagogy:config_edit")).status_code, 403)
        self.login("sec")
        resp = self.client.post(
            reverse("pedagogy:config_edit"),
            {"_config": "1", "max_absences_percent": "20.0"},
            follow=True,
        )
        self.assertEqual(self.school.config.max_absences_percent, 20.0)
        self.login("coord")
        self.assertEqual(self.client.get(reverse("pedagogy:config_edit")).status_code, 403)

    def test_academic_rule_saved_per_subject(self):
        self.login("sec")
        self.client.post(
            reverse("pedagogy:academic_rule_edit", args=[self.mat.pk]),
            {"subject": self.mat.pk, "formula": "ponderada", "passing_grade": "7.00"},
            follow=True,
        )
        rule = AcademicRule.objects.get(school=self.school, subject=self.mat)
        self.assertEqual(rule.formula, "ponderada")
        self.assertEqual(float(rule.passing_grade), 7.0)

    def test_academic_rule_unique_per_subject(self):
        AcademicRule.objects.create(
            school=self.school, subject=self.mat, formula="aritmetica"
        )
        self.login("sec")
        self.client.post(
            reverse("pedagogy:academic_rule_edit", args=[self.mat.pk]),
            {"subject": self.mat.pk, "formula": "soma", "passing_grade": "6.00"},
            follow=True,
        )
        self.assertEqual(AcademicRule.objects.filter(subject=self.mat).count(), 1)


class AttendanceClassAccessTests(PedagogyBase):
    def test_professor_only_own_class(self):
        self.login("prof")
        self.assertEqual(
            self.client.get(
                reverse("pedagogy:attendance_class", args=[self.turma.pk])
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse("pedagogy:attendance_class", args=[self.turma_b.pk])
            ).status_code,
            403,
        )

    def test_staff_views_any_class_in_school(self):
        self.login("coord")
        self.assertEqual(
            self.client.get(
                reverse("pedagogy:attendance_class", args=[self.turma_b.pk])
            ).status_code,
            200,
        )


class CrossSchoolTests(PedagogyBase):
    def test_other_school_user_cannot_access_school_data(self):
        self.login("prof_b")
        resp = self.client.get(reverse("pedagogy:evaluation_list"))
        self.assertNotContains(resp, "Prova de Matemática")
        self.assertEqual(resp.status_code, 200)

    def test_other_school_user_cannot_manage_here(self):
        from ..models import Evaluation as E
        ev = E.objects.create(
            school=self.school, subject=self.mat, class_group=self.turma,
            title="Prova", created_by=self.prof,
        )
        self.login("prof_b")
        self.assertEqual(
            self.client.get(reverse("pedagogy:evaluation_grade", args=[ev.pk])).status_code,
            404,  # get_object_or_404 com filtro school não encontra
        )