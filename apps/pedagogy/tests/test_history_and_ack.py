"""Prompt 10, terceira rodada (02/11/2026).

- Histórico de alterações: editar uma atividade publicada registra o que
  mudou; a família vê que mudou (e quando), a equipe vê de quê para quê.
- "Estou ciente": confirmação de leitura explícita, por estudante, que não
  conclui a tarefa e não abre dado de outro estudante.
- Remoção de anexo enviado por engano, só por quem gerencia a atividade.
- Controle de entregas: "sem registro" num estudante que já tem registro
  mantém o registro, e a tela diz isso.
"""

import os
import tempfile
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditLog, Role, User
from apps.registry.models import Enrollment, GuardianLink, Student

from ..models import (
    Activity,
    ActivityAcknowledgement,
    ActivityAttachment,
    ActivityChange,
    Submission,
)
from .test_pedagogy import PedagogyBase


class Base(PedagogyBase):
    def make_activity(self, **extra):
        data = dict(
            school=self.school, class_group=self.turma, subject=self.mat,
            title="Dever cap. 2", description="Ler o capítulo 2.",
            created_by=self.prof, status=Activity.Status.PUBLISHED,
            published_date=timezone.localdate() - timedelta(days=2),
            deadline=timezone.localdate() + timedelta(days=5),
            class_date=timezone.localdate(),
        )
        data.update(extra)
        return Activity.objects.create(**data)

    def edit(self, act, **changes):
        data = {
            "class_group": act.class_group_id,
            "subject": act.subject_id,
            "title": act.title,
            "description": act.description,
            "materials": act.materials,
            "internal_notes": act.internal_notes,
            "published_date": f"{act.published_date:%Y-%m-%d}",
            "deadline": f"{act.deadline:%Y-%m-%d}" if act.deadline else "",
            "class_date": f"{act.class_date:%Y-%m-%d}" if act.class_date else "",
            "work_mode": act.work_mode,
        }
        data.update(changes)
        self.login("prof")
        resp = self.client.post(reverse("pedagogy:activity_edit", args=[act.pk]), data)
        self.assertEqual(resp.status_code, 302, getattr(resp, "context", None) and resp.context["form"].errors)
        self.client.logout()
        act.refresh_from_db()
        return act


class ActivityHistoryTests(Base):
    def test_editing_published_activity_records_what_changed(self):
        act = self.make_activity()
        nova = timezone.localdate() + timedelta(days=9)
        self.edit(act, description="Ler o capítulo 3.", deadline=f"{nova:%Y-%m-%d}")
        change = ActivityChange.objects.get(activity=act)
        self.assertTrue(change.family_saw)
        self.assertEqual(change.changed_by, self.prof)
        por_rotulo = {f["label"]: f for f in change.fields}
        self.assertEqual(set(por_rotulo), {"Instruções", "Data de entrega"})
        self.assertEqual(por_rotulo["Instruções"]["before"], "Ler o capítulo 2.")
        self.assertEqual(por_rotulo["Instruções"]["after"], "Ler o capítulo 3.")
        self.assertEqual(por_rotulo["Data de entrega"]["after"], f"{nova:%d/%m/%Y}")
        log = AuditLog.objects.filter(action="update", target_id=str(act.pk)).latest("created_at")
        self.assertIn("instruções", log.detail)
        self.assertIn("data de entrega", log.detail)

    def test_saving_without_changes_records_nothing(self):
        act = self.make_activity()
        self.edit(act)
        self.assertFalse(ActivityChange.objects.exists())

    def test_draft_edits_have_no_history(self):
        act = self.make_activity(status=Activity.Status.DRAFT)
        self.edit(act, description="Outra coisa.")
        self.assertFalse(ActivityChange.objects.exists())

    def test_scheduled_edit_is_recorded_as_not_seen_by_family(self):
        act = self.make_activity(published_date=timezone.localdate() + timedelta(days=3),
                                 deadline=timezone.localdate() + timedelta(days=8))
        self.edit(act, description="Outra coisa.")
        self.assertFalse(ActivityChange.objects.get().family_saw)

    def test_family_sees_that_it_changed_but_not_the_old_text(self):
        act = self.make_activity()
        self.edit(act, description="Ler o capítulo 3.")
        self.login("resp")
        detalhe = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        self.assertContains(detalhe, "foi alterada depois de publicada")
        self.assertContains(detalhe, "instruções")
        self.assertContains(detalhe, "Ler o capítulo 3.")
        self.assertNotContains(detalhe, "Ler o capítulo 2.")
        self.assertNotContains(detalhe, "Histórico de alterações")
        lista = self.client.get(reverse("pedagogy:activity_list"))
        self.assertContains(lista, "Alterada em")

    def test_internal_notes_change_is_invisible_to_family(self):
        act = self.make_activity()
        self.edit(act, internal_notes="Conferir a aluna X.")
        self.assertEqual(ActivityChange.objects.get().family_labels, [])
        self.login("resp")
        detalhe = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        self.assertNotContains(detalhe, "foi alterada")
        self.assertNotContains(detalhe, "Conferir a aluna X.")
        self.assertNotContains(self.client.get(reverse("pedagogy:activity_list")), "Alterada em")

    def test_staff_sees_before_and_after(self):
        act = self.make_activity()
        self.edit(act, description="Ler o capítulo 3.")
        for user in ("prof", "coord"):
            self.login(user)
            detalhe = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
            self.assertContains(detalhe, "Histórico de alterações")
            self.assertContains(detalhe, "Ler o capítulo 2.")
            self.client.logout()


class AcknowledgementTests(Base):
    def ack(self, act, student, user="resp"):
        self.login(user)
        return self.client.post(
            reverse("pedagogy:activity_acknowledge", args=[act.pk]), {"estudante": student.pk}
        )

    def test_guardian_acknowledges_for_own_child(self):
        act = self.make_activity()
        self.login("resp")
        self.assertContains(
            self.client.get(reverse("pedagogy:activity_detail", args=[act.pk])), "Estou ciente"
        )
        resp = self.ack(act, self.ana)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ActivityAcknowledgement.objects.get().user, self.resp)
        # De novo: continua um registro só.
        self.ack(act, self.ana)
        self.assertEqual(ActivityAcknowledgement.objects.count(), 1)
        detalhe = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        self.assertContains(detalhe, "Ciente em")
        self.assertNotContains(detalhe, "Estou ciente</button>")
        self.assertContains(self.client.get(reverse("pedagogy:activity_list")), "✓ Ciente")

    def test_acknowledging_does_not_complete_the_activity(self):
        act = self.make_activity()
        self.ack(act, self.ana)
        self.assertFalse(Submission.objects.exists())
        self.assertEqual(act.family_situation()[0], "pendente")

    def test_teacher_sees_who_is_aware(self):
        act = self.make_activity()
        self.ack(act, self.ana)
        self.client.logout()
        self.login("prof")
        entregas = self.client.get(reverse("pedagogy:activity_submissions", args=[act.pk]))
        self.assertContains(entregas, "Família ciente")
        self.assertContains(entregas, "(responsável)")
        detalhe = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        self.assertContains(detalhe, "Família ciente: <strong>1</strong>")

    def test_cannot_acknowledge_for_unlinked_student(self):
        """Bea é de outra turma e não é filha de resp: trocar o id não adianta."""
        act = self.make_activity()
        self.assertEqual(self.ack(act, self.bea).status_code, 403)
        # Colega da mesma turma, sem vínculo com resp.
        colega = Student.objects.create(school=self.school, first_name="Duda")
        Enrollment.objects.create(school=self.school, student=colega,
                                  class_group=self.turma, school_year=self.year)
        self.assertEqual(self.ack(act, colega).status_code, 403)
        self.assertFalse(ActivityAcknowledgement.objects.exists())

    def test_pending_link_cannot_acknowledge(self):
        act = self.make_activity()
        GuardianLink.objects.filter(guardian=self.resp).update(status="pendente")
        self.assertEqual(self.ack(act, self.ana).status_code, 403)
        self.assertFalse(ActivityAcknowledgement.objects.exists())

    def test_get_and_staff_cannot_acknowledge(self):
        act = self.make_activity()
        self.login("resp")
        get = self.client.get(reverse("pedagogy:activity_acknowledge", args=[act.pk]),
                              {"estudante": self.ana.pk})
        self.assertEqual(get.status_code, 403)
        self.assertEqual(self.ack(act, self.ana, user="prof").status_code, 403)
        self.assertFalse(ActivityAcknowledgement.objects.exists())

    def test_draft_and_canceled_cannot_be_acknowledged(self):
        rascunho = self.make_activity(status=Activity.Status.DRAFT)
        self.assertEqual(self.ack(rascunho, self.ana).status_code, 403)
        cancelada = self.make_activity()
        cancelada.cancel("Sem aula")
        cancelada.save()
        self.assertEqual(self.ack(cancelada, self.ana).status_code, 302)
        self.assertFalse(ActivityAcknowledgement.objects.exists())

    def test_student_from_after_the_activity_cannot_acknowledge_old_one(self):
        """Quem entrou depois do prazo não recebeu a atividade: nada a confirmar."""
        act = self.make_activity(published_date=date(2026, 3, 1), deadline=date(2026, 3, 5))
        Enrollment.objects.filter(student=self.ana).update(started_on=date(2026, 4, 1))
        self.assertEqual(self.ack(act, self.ana).status_code, 403)

    def test_two_children_each_get_their_own_button(self):
        caio = Student.objects.create(school=self.school, first_name="Caio")
        Enrollment.objects.create(school=self.school, student=caio,
                                  class_group=self.turma, school_year=self.year)
        GuardianLink.objects.create(school=self.school, guardian=self.resp,
                                    student=caio, status="aprovado")
        act = self.make_activity()
        self.login("resp")
        detalhe = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        self.assertContains(detalhe, "Estou ciente (Ana)")
        self.assertContains(detalhe, "Estou ciente (Caio)")
        self.ack(act, caio)
        self.assertEqual(
            list(ActivityAcknowledgement.objects.values_list("student_id", flat=True)), [caio.pk]
        )

    def test_student_account_acknowledges_itself_only(self):
        conta = User.objects.create_user(username="aluna", password="senha-forte-1",
                                         role=Role.ESTUDANTE, school=self.school)
        self.ana.user = conta
        self.ana.save(update_fields=["user"])
        act = self.make_activity()
        self.assertEqual(self.ack(act, self.ana, user="aluna").status_code, 302)
        self.assertEqual(self.ack(act, self.bea, user="aluna").status_code, 403)
        self.assertEqual(ActivityAcknowledgement.objects.get().student, self.ana)
        self.login("prof")
        self.assertContains(
            self.client.get(reverse("pedagogy:activity_submissions", args=[act.pk])),
            "(estudante)",
        )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="escola-test-media-"))
class AttachmentRemovalTests(Base):
    def make_with_attachment(self, **extra):
        act = self.make_activity(**extra)
        att = ActivityAttachment.objects.create(
            activity=act, file=SimpleUploadedFile("dados.pdf", b"%PDF-1.4 x"),
            original_name="dados.pdf", size=10, uploaded_by=self.prof,
        )
        return act, att

    def remove(self, act, att, user="prof"):
        self.login(user)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                reverse("pedagogy:activity_attachment_remove", args=[act.pk, att.pk])
            )

    def test_manager_removes_attachment_file_and_all(self):
        act, att = self.make_with_attachment()
        path = att.file.path
        self.assertTrue(os.path.exists(path))
        self.assertEqual(self.remove(act, att).status_code, 302)
        self.assertFalse(ActivityAttachment.objects.exists())
        self.assertFalse(os.path.exists(path))
        change = ActivityChange.objects.get()
        self.assertEqual(change.fields[0]["label"], "Anexo removido")
        self.assertEqual(change.fields[0]["before"], "dados.pdf")
        self.assertTrue(
            AuditLog.objects.filter(action="delete", detail__contains="dados.pdf").exists()
        )
        self.login("resp")
        self.assertEqual(
            self.client.get(reverse("pedagogy:activity_attachment", args=[act.pk, att.pk])).status_code,
            404,
        )

    def test_removal_also_works_on_canceled_activity(self):
        act, att = self.make_with_attachment()
        act.cancel("Arquivo errado")
        act.save()
        self.assertEqual(self.remove(act, att).status_code, 302)
        self.assertFalse(ActivityAttachment.objects.exists())

    def test_others_cannot_remove(self):
        act, att = self.make_with_attachment()
        for user in ("prof2", "resp", "coord", "sec"):
            self.assertEqual(self.remove(act, att, user=user).status_code, 403, user)
            self.client.logout()
        self.login("prof")
        get = self.client.get(reverse("pedagogy:activity_attachment_remove", args=[act.pk, att.pk]))
        self.assertEqual(get.status_code, 403)
        self.assertTrue(ActivityAttachment.objects.exists())

    def test_attachment_id_of_another_activity_is_refused(self):
        act, _ = self.make_with_attachment()
        outra, att_outra = self.make_with_attachment(title="Outra")
        self.login("prof")
        resp = self.client.post(
            reverse("pedagogy:activity_attachment_remove", args=[act.pk, att_outra.pk])
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(ActivityAttachment.objects.count(), 2)

    def test_attachment_added_on_edit_enters_history(self):
        act = self.make_activity()
        self.edit(act, attachments=SimpleUploadedFile("novo.pdf", b"%PDF-1.4 y",
                                                      content_type="application/pdf"))
        labels = [f["label"] for f in ActivityChange.objects.get().fields]
        self.assertEqual(labels, ["Anexo incluído"])


class KeepExistingSubmissionTests(Base):
    def test_blank_status_keeps_saved_record_and_says_so(self):
        act = self.make_activity()
        Submission.objects.create(school=self.school, activity=act, student=self.ana,
                                  status=Submission.Status.DELIVERED)
        self.login("prof")
        tela = self.client.get(reverse("pedagogy:activity_submissions", args=[act.pk]))
        self.assertContains(tela, "— manter o registro salvo —")
        self.client.post(reverse("pedagogy:activity_submissions", args=[act.pk]),
                         {f"status_{self.ana.pk}": ""})
        self.assertEqual(Submission.objects.get().status, Submission.Status.DELIVERED)
