from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification

from ..models import (
    AbsenceJustification,
    Activity,
    AttendanceRecord,
    Evaluation,
    GroupWork,
    Occurrence,
    PedagogicalObservation,
)
from .test_pedagogy import PedagogyBase


class SecurityRemediationTests(PedagogyBase):
    def test_guardian_cannot_filter_occurrences_by_another_student(self):
        Occurrence.objects.create(
            school=self.school,
            student=self.bea,
            date=timezone.localdate(),
            description="Ocorrência da Beatriz",
            recorded_by=self.prof,
        )
        self.login("resp")
        resp = self.client.get(
            reverse("pedagogy:occurrence_list"),
            {"estudante": self.bea.pk},
        )
        self.assertEqual(resp.status_code, 403)

    def test_observation_edit_action_only_for_author_or_coordination(self):
        PedagogicalObservation.objects.create(
            school=self.school,
            student=self.ana,
            teacher=self.prof2,
            content="Registro de outro professor",
            observed_at=timezone.localdate(),
        )
        self.login("prof")
        resp = self.client.get(
            reverse("pedagogy:observation_list"), {"estudante": self.ana.pk}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(
            resp,
            reverse(
                "pedagogy:observation_edit",
                args=[PedagogicalObservation.objects.get().pk],
            ),
        )

    def test_evaluation_create_forces_draft_even_with_crafted_status(self):
        self.login("prof")
        self.client.post(
            reverse("pedagogy:evaluation_create"),
            {
                "class_group": self.turma.pk,
                "subject": self.mat.pk,
                "title": "Prova forçada",
                "weight": "2.00",
                "date": "2026-03-15",
                "status": Evaluation.Status.PUBLISHED,
            },
        )
        ev = Evaluation.objects.get(title="Prova forçada")
        self.assertEqual(ev.status, Evaluation.Status.DRAFT)

    def test_publish_is_idempotent_and_does_not_duplicate_notifications(self):
        ev = self.make_evaluation()
        self.login("prof")
        url = reverse("pedagogy:evaluation_publish", args=[ev.pk])
        self.client.post(url)
        first_count = Notification.objects.filter(
            user=self.resp, kind=Notification.Kind.EVALUATION
        ).count()
        self.assertGreater(first_count, 0)
        self.client.post(url)
        self.assertEqual(
            Notification.objects.filter(
                user=self.resp, kind=Notification.Kind.EVALUATION
            ).count(),
            first_count,
        )

    def test_resolved_justification_cannot_change_decision(self):
        justification = AbsenceJustification.objects.create(
            school=self.school,
            student=self.ana,
            class_group=self.turma,
            start_date="2026-03-02",
            end_date="2026-03-02",
            reason="Consulta médica",
            submitted_by=self.resp,
        )
        self.login("sec")
        self.client.post(
            reverse(
                "pedagogy:justification_resolve",
                args=[justification.pk, "aprovar"],
            )
        )
        justification.refresh_from_db()
        self.assertEqual(justification.status, AbsenceJustification.Status.APPROVED)
        self.client.post(
            reverse(
                "pedagogy:justification_resolve",
                args=[justification.pk, "recusar"],
            )
        )
        justification.refresh_from_db()
        self.assertEqual(justification.status, AbsenceJustification.Status.APPROVED)

    def test_justification_rejects_class_without_student_enrollment(self):
        self.login("resp")
        self.client.post(
            reverse("pedagogy:justification_create"),
            {
                "student_id": self.ana.pk,
                "class_group": self.turma_b.pk,
                "start_date": "2026-03-02",
                "end_date": "2026-03-02",
                "reason": "Consulta médica",
            },
        )
        self.assertFalse(
            AbsenceJustification.objects.filter(
                student=self.ana, class_group=self.turma_b
            ).exists()
        )


class AttendanceRemediationTests(PedagogyBase):
    def test_future_attendance_is_rejected(self):
        self.login("prof")
        future = timezone.localdate() + timedelta(days=7)
        resp = self.client.post(
            reverse("pedagogy:attendance_register", args=[self.turma.pk]),
            {
                "date": future.isoformat(),
                f"status_{self.ana.pk}": "presente",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            AttendanceRecord.objects.filter(date=future, student=self.ana).exists()
        )

    def test_form_prefills_only_the_selected_date(self):
        AttendanceRecord.objects.create(
            school=self.school,
            class_group=self.turma,
            student=self.ana,
            date=date(2026, 3, 10),
            status=AttendanceRecord.Status.ABSENT,
            recorded_by=self.prof,
        )
        self.login("prof")
        resp = self.client.get(
            reverse("pedagogy:attendance_register", args=[self.turma.pk]),
            {"data": "2026-03-11"},
        )
        field = resp.context["form"].fields[f"status_{self.ana.pk}"]
        self.assertEqual(field.initial, "presente")


class FamilyCanceledRecordTests(PedagogyBase):
    def test_guardian_can_open_canceled_activity_after_publication(self):
        activity = Activity.objects.create(
            school=self.school,
            class_group=self.turma,
            subject=self.mat,
            title="Tarefa cancelada",
            description="Conteúdo",
            published_date=timezone.localdate(),
            status=Activity.Status.CANCELED,
            cancel_reason="Mudança de calendário",
        )
        self.login("resp")
        self.assertEqual(
            self.client.get(
                reverse("pedagogy:activity_detail", args=[activity.pk])
            ).status_code,
            200,
        )

    def test_guardian_can_open_canceled_group_work_after_publication(self):
        work = GroupWork.objects.create(
            school=self.school,
            class_group=self.turma,
            subject=self.mat,
            title="Trabalho cancelado",
            description="Conteúdo",
            published_date=timezone.localdate(),
            status=GroupWork.Status.CANCELED,
            cancel_reason="Mudança de calendário",
        )
        self.login("resp")
        self.assertEqual(
            self.client.get(
                reverse("pedagogy:group_work_detail", args=[work.pk])
            ).status_code,
            200,
        )
