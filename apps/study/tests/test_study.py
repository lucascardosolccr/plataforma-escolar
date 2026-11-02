"""Conteúdos da prova (Prompt 18 §10) e os cenários do §20 que dependem deles.

Os números "(§20.n)" indicam o cenário obrigatório coberto por cada teste.
"""

import os
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.cognitio.evidence import rebuild_class
from apps.cognitio.models import MasteryScale, SkillJudgment, SkillRelation
from apps.cognitio.tests.test_p17 import P17Base
from apps.communication.models import Notification
from apps.core.models import Role, User

from .. import plan
from ..models import ExamGuide, ExamTopic, GuideUpdate, StudyMaterial, StudyQuestion, TopicCheck

PW = "Senha-forte-123"
MEDIA = tempfile.mkdtemp(prefix="escola-study-")


@override_settings(MEDIA_ROOT=MEDIA)
class StudyBase(P17Base):
    def setUp(self):
        super().setUp()
        self.conta = User.objects.create_user("ana.aluna", password=PW, role=Role.ESTUDANTE, school=self.school)
        self.ana.user = self.conta
        self.ana.save(update_fields=["user"])

    def guide(self, publish=True, **extra):
        data = dict(school=self.school, class_group=self.cg, subject=self.mat, title="Prova de números",
                    exam_date=self.today + timedelta(days=10), created_by=self.prof,
                    status=ExamGuide.Status.PUBLISHED if publish else ExamGuide.Status.DRAFT)
        data.update(extra)
        g = ExamGuide.objects.create(**data)
        t = ExamTopic.objects.create(guide=g, title="Operações", priority="alta")
        t.curriculum.add(self.h2)
        self.topic = t
        return g

    def post_guide(self, **extra):
        self.login(self.prof)
        data = {"class_group": self.cg.pk, "subject": self.mat.pk, "title": "Prova de números",
                "exam_date": f"{self.today + timedelta(days=10):%Y-%m-%d}"}
        data.update(extra)
        return self.client.post(reverse("study:create"), data)


class GuideFlowTests(StudyBase):
    def test_teacher_creates_publishes_and_class_is_notified(self):
        """§20.7: publicado para a turma certa, avisado uma vez."""
        r = self.post_guide()
        self.assertEqual(r.status_code, 302)
        g = ExamGuide.objects.get()
        self.assertEqual(g.status, ExamGuide.Status.DRAFT)
        # Sem tópico não publica.
        self.client.post(reverse("study:status", args=[g.pk, "publicar"]))
        g.refresh_from_db()
        self.assertEqual(g.status, ExamGuide.Status.DRAFT)
        self.client.post(reverse("study:topic_add", args=[g.pk]), {"title": "Operações", "priority": "alta",
                                                                   "curriculum": [self.h2.pk], "order": 1})
        self.assertEqual(list(g.curriculum.all()), [self.h2])  # habilidades da prova = dos tópicos
        self.client.post(reverse("study:status", args=[g.pk, "publicar"]))
        g.refresh_from_db()
        self.assertEqual(g.status, ExamGuide.Status.PUBLISHED)
        avisos = Notification.objects.filter(title__startswith="Conteúdos da prova")
        self.assertTrue(avisos.filter(user=self.fam).exists())
        self.assertTrue(avisos.filter(user=self.conta).exists())
        n = avisos.count()
        self.client.post(reverse("study:status", args=[g.pk, "arquivar"]))
        self.client.post(reverse("study:status", args=[g.pk, "reabrir"]))
        self.assertEqual(avisos.count(), n)  # republicar não avisa de novo

    def test_teacher_cannot_create_for_other_class(self):
        r = self.post_guide(class_group=self.cg_b.pk)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(ExamGuide.objects.exists())

    def test_family_and_other_class_access(self):
        """§20.7 e §20.8: estudante e família da turma veem; outra turma não; rascunho não."""
        g = self.guide()
        for user in (self.conta, self.fam):
            self.login(user)
            self.assertEqual(self.client.get(reverse("study:detail", args=[g.pk])).status_code, 200)
            self.assertContains(self.client.get(reverse("study:list")), "Prova de números")
        outra = User.objects.create_user("bia.b", password=PW, role=Role.ESTUDANTE, school=self.school)
        from apps.registry.models import Enrollment, Student

        bia_b = Student.objects.create(school=self.school, first_name="Beatriz", user=outra)
        Enrollment.objects.create(school=self.school, student=bia_b, class_group=self.cg_b,
                                  school_year=self.cg_b.school_year)
        for user in (outra, self.sec, self.prof_b):
            self.login(user)
            self.assertEqual(self.client.get(reverse("study:detail", args=[g.pk])).status_code, 403, user.username)
        rascunho = self.guide(publish=False, title="Ainda não")
        self.login(self.conta)
        self.assertEqual(self.client.get(reverse("study:detail", args=[rascunho.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("study:list")), "Ainda não")

    def test_scheduled_guide_is_hidden_and_announced_on_its_day(self):
        g = self.guide(published_date=self.today + timedelta(days=2))
        self.login(self.conta)
        self.assertEqual(self.client.get(reverse("study:detail", args=[g.pk])).status_code, 403)
        from ..services import deliver_due_guides

        self.assertEqual(deliver_due_guides(), 0)
        ExamGuide.objects.filter(pk=g.pk).update(published_date=self.today)
        self.assertEqual(deliver_due_guides(), 1)
        self.assertEqual(deliver_due_guides(), 0)

    def test_archive_keeps_history(self):
        """§20.27: arquivar tira das listas sem apagar."""
        g = self.guide()
        StudyQuestion.objects.create(guide=g, student=self.ana, author=self.conta, text="Como divide?")
        self.login(self.prof)
        self.client.post(reverse("study:status", args=[g.pk, "arquivar"]))
        self.login(self.conta)
        self.assertEqual(self.client.get(reverse("study:detail", args=[g.pk])).status_code, 403)
        self.assertEqual(StudyQuestion.objects.count(), 1)
        self.login(self.prof)
        self.assertContains(self.client.get(reverse("study:detail", args=[g.pk])), "Como divide?")


@override_settings(MEDIA_ROOT=MEDIA)
class MaterialTests(StudyBase):
    def add(self, g, **data):
        self.login(self.prof)
        return self.client.post(reverse("study:material_add", args=[g.pk]), data)

    def test_invalid_video_url_is_refused(self):
        """§20.9."""
        g = self.guide()
        r = self.add(g, kind="video", title="Vídeo", url="javascript:alert(1)")
        self.assertEqual(r.status_code, 200)
        r = self.add(g, kind="video", title="Vídeo", url="")
        self.assertIn("url", r.context["form"].errors)
        r = self.add(g, kind="video", title="Frações", url="https://www.youtube.com/watch?v=abc", order=0)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(StudyMaterial.objects.get().platform, "YouTube")

    def test_reading_needs_enough_information(self):
        """§20.12: sem autor nem editora não entra; 'livre' sem link também não."""
        g = self.guide()
        r = self.add(g, kind="leitura", title="Livro de Matemática")
        self.assertIn("author", r.context["form"].errors)
        r = self.add(g, kind="leitura", title="Livro", author="Fulano", access_type="livre")
        self.assertIn("access_type", r.context["form"].errors)
        self.assertFalse(StudyMaterial.objects.exists())

    def test_file_is_protected_and_replacement_is_tracked(self):
        """§20.10 e §20.20: arquivo só por quem pode ver; trocado some da lista e fica no histórico."""
        from ..services import announce

        g = self.guide()
        announce(g)
        self.add(g, kind="arquivo", title="Lista 1", order=0,
                 file=SimpleUploadedFile("lista.pdf", b"%PDF-1.4 x", content_type="application/pdf"))
        old = StudyMaterial.objects.get()
        url_old = reverse("study:material_file", args=[g.pk, old.pk])
        self.login(self.conta)
        self.assertEqual(self.client.get(url_old).status_code, 200)
        for user in (self.sec, self.prof_b):
            self.login(user)
            self.assertEqual(self.client.get(url_old).status_code, 403)
        self.login(self.prof)
        r = self.client.post(reverse("study:material_replace", args=[g.pk, old.pk]), {
            "kind": "arquivo", "title": "Lista 1 corrigida", "order": 0,
            "file": SimpleUploadedFile("lista2.pdf", b"%PDF-1.4 y", content_type="application/pdf")})
        self.assertEqual(r.status_code, 302)
        old.refresh_from_db()
        self.assertIsNotNone(old.removed_at)
        self.assertEqual(old.replaced_by.title, "Lista 1 corrigida")
        self.assertTrue(GuideUpdate.objects.filter(kind="material_trocado").exists())
        self.login(self.conta)
        page = self.client.get(reverse("study:detail", args=[g.pk]))
        self.assertContains(page, "Lista 1 corrigida")
        self.assertNotContains(page, f"materiais/{old.pk}/arquivo")
        self.assertEqual(self.client.get(url_old).status_code, 404)
        self.assertTrue(Notification.objects.filter(user=self.conta, title__startswith="Conteúdos da prova atualizados")
                        .exists())

    def test_executable_disguised_as_pdf_is_refused(self):
        g = self.guide()
        r = self.add(g, kind="arquivo", title="x", order=0,
                     file=SimpleUploadedFile("x.pdf", b"MZ\x90\x00", content_type="application/pdf"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(StudyMaterial.objects.exists())

    def test_family_reports_broken_link_and_teacher_is_told(self):
        g = self.guide()
        m = StudyMaterial.objects.create(guide=g, kind="link", title="Página", url="https://exemplo.org/x")
        self.login(self.fam)
        self.client.post(reverse("study:material_report", args=[g.pk, m.pk]))
        self.client.post(reverse("study:material_report", args=[g.pk, m.pk]))
        m.refresh_from_db()
        self.assertEqual(m.broken_reports, 2)
        self.assertEqual(Notification.objects.filter(user=self.prof, title__startswith="Link que não abre").count(), 1)

    def test_accessibility_note_reaches_the_student(self):
        """§20.24: a alternativa acessível indicada pelo professor aparece ao estudante."""
        g = self.guide()
        StudyMaterial.objects.create(guide=g, kind="video", title="Vídeo", url="https://vimeo.com/1",
                                     accessibility="Legendas em português e transcrição no PDF anexo")
        self.login(self.conta)
        self.assertContains(self.client.get(reverse("study:detail", args=[g.pk])), "Legendas em português")


class DateAndConcurrencyTests(StudyBase):
    def test_date_change_updates_and_notifies(self):
        """§20.11: mudar a data (na prova ou na avaliação ligada) avisa uma vez por data."""
        g = self.guide(evaluation=self.ev, exam_date=self.ev.date)
        from ..services import announce, sync_evaluation_date

        announce(g)
        old = self.ev.date
        self.ev.date = old + timedelta(days=3)
        self.ev.save()
        sync_evaluation_date(self.ev, old, self.prof)
        g.refresh_from_db()
        self.assertEqual(g.exam_date, self.ev.date)
        self.assertEqual(Notification.objects.filter(user=self.conta, title__startswith="Data da prova").count(), 1)
        self.assertTrue(g.updates.filter(kind="data").exists())

    def test_evaluation_date_in_form_wins(self):
        r = self.post_guide(evaluation=self.ev.pk, exam_date=f"{self.today + timedelta(days=40):%Y-%m-%d}")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(ExamGuide.objects.get().exam_date, self.ev.date)

    def test_two_people_editing_the_same_guide(self):
        """§20.19: quem salva por último com versão velha é avisado e nada é gravado."""
        g = self.guide()
        self.login(self.prof)
        base = {"subject": self.mat.pk, "exam_date": f"{g.exam_date:%Y-%m-%d}", "version": g.version}
        r = self.client.post(reverse("study:edit", args=[g.pk]), {**base, "title": "Primeira"})
        self.assertEqual(r.status_code, 302)
        r = self.client.post(reverse("study:edit", args=[g.pk]), {**base, "title": "Segunda"})
        g.refresh_from_db()
        self.assertEqual(g.title, "Primeira")
        self.assertEqual(r.status_code, 200)  # formulário com o aviso

    def test_invalid_save_keeps_data_and_writes_nothing(self):
        """§20.18: erro de validação devolve o que foi digitado e não grava pela metade."""
        r = self.post_guide(title="Prova X", available_until=f"{self.today:%Y-%m-%d}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'value="Prova X"')
        self.assertFalse(ExamGuide.objects.exists())


class SelfReportAndQuestionsTests(StudyBase):
    def test_student_marks_topics_and_asks(self):
        g = self.guide()
        self.login(self.conta)
        self.client.post(reverse("study:topic_check", args=[g.pk, self.topic.pk]), {"status": "praticar"})
        self.assertEqual(TopicCheck.objects.get().status, "praticar")
        self.client.post(reverse("study:question_add", args=[g.pk]), {"text": "Como faço a prova real?",
                                                                       "topic": self.topic.pk})
        q = StudyQuestion.objects.get()
        self.assertEqual((q.student, q.author), (self.ana, self.conta))
        self.assertTrue(Notification.objects.filter(user=self.prof, title__startswith="Nova dúvida").exists())
        self.login(self.prof)
        self.client.post(reverse("study:question_answer", args=[g.pk, q.pk]), {"answer": "Multiplique o quociente."})
        q.refresh_from_db()
        self.assertEqual(q.answered_by, self.prof)
        self.login(self.fam)
        page = self.client.get(reverse("study:detail", args=[g.pk]))
        self.assertContains(page, "Multiplique o quociente.")
        self.assertContains(page, "Preciso praticar")

    def test_only_the_student_marks_and_guardian_cannot_ask_for_other_child(self):
        g = self.guide()
        self.login(self.fam)
        r = self.client.post(reverse("study:topic_check", args=[g.pk, self.topic.pk]), {"status": "entendi"})
        self.assertEqual(r.status_code, 403)
        r = self.client.post(reverse("study:question_add", args=[g.pk]), {"text": "x", "estudante": self.bia.pk})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(StudyQuestion.objects.exists())

    def test_self_report_does_not_become_evidence(self):
        """§20.13: 'entendi' com erros nos exercícios continua em desenvolvimento para o professor."""
        g = self.guide()
        self.obs(self.ana, self.h2, 1, 3, context="Exercício A")
        self.obs(self.ana, self.h2, 2, 1, context="Exercício B")
        rebuild_class(self.cg)
        TopicCheck.objects.create(topic=self.topic, student=self.ana, status="entendi")
        p = plan.preparation_plan(g, self.ana, detailed=True)
        topic_step = [s for s in p["steps"] if s["topic"] == self.topic][0]
        self.assertEqual(topic_step["kind"], "estudar")
        self.login(self.prof)
        page = self.client.get(reverse("study:student_plan", args=[g.pk, self.ana.pk]))
        self.assertContains(page, "Autorrelato do estudante: Entendi")


class PreparationPlanTests(StudyBase):
    """§20.1–6, §20.14, §20.15 e §20.28."""

    def steps(self, g, student):
        return plan.preparation_plan(g, student, detailed=True)

    def test_no_data_gives_general_plan(self):  # §20.3
        p = self.steps(self.guide(), self.ana)
        self.assertFalse(p["personalized"])
        self.assertIn("Plano geral", p["note"])

    def test_confirmed_gap_in_foundation_comes_first(self):  # §20.2 e §20.15
        g = self.guide()
        for ctx, d in (("Quadro", 6), ("Prova oral", 2)):
            self.obs(self.ana, self.h1, 1, d, context=ctx)
        self.obs(self.ana, self.h2, 1, 3, context="Lista")
        self.obs(self.ana, self.h2, 2, 1, context="Prova")
        rebuild_class(self.cg)
        p = self.steps(g, self.ana)
        self.assertTrue(p["personalized"])
        self.assertEqual(p["steps"][0]["kind"], "retomar")
        self.assertEqual(p["steps"][0]["code"], self.h1.code)

    def test_all_prerequisites_mastered(self):  # §20.1
        g = self.guide()
        for ctx, d in (("A", 6), ("B", 4), ("C", 2)):
            self.obs(self.ana, self.h1, 4, d, context=ctx)
        self.obs(self.ana, self.h2, 1, 3, context="Lista")
        self.obs(self.ana, self.h2, 2, 1, context="Prova")
        rebuild_class(self.cg)
        kinds = [s["kind"] for s in self.steps(g, self.ana)["steps"]]
        self.assertNotIn("retomar", kinds)
        self.assertNotIn("verificar", kinds)

    def test_missing_evidence_is_a_check_not_a_gap(self):  # §20.5
        g = self.guide()
        self.obs(self.ana, self.h2, 1, 3, context="Lista")
        self.obs(self.ana, self.h2, 2, 1, context="Prova")
        rebuild_class(self.cg)
        first = self.steps(g, self.ana)["steps"][0]
        self.assertEqual(first["kind"], "verificar")
        fam = plan.preparation_plan(g, self.ana, detailed=False)["steps"][0]
        self.assertIn("Ainda não há registro", fam["reason"])

    def test_contradictory_records_ask_for_verification(self):  # §20.4
        g = self.guide()
        self.obs(self.ana, self.h1, 1, 6, context="A")
        self.obs(self.ana, self.h1, 4, 4, context="B")
        self.obs(self.ana, self.h1, 1, 2, context="C")
        self.obs(self.ana, self.h1, 4, 1, context="D")
        self.obs(self.ana, self.h2, 1, 3, context="Lista")
        self.obs(self.ana, self.h2, 2, 1, context="Prova")
        rebuild_class(self.cg)
        first = self.steps(g, self.ana)["steps"][0]
        self.assertNotEqual(first["kind"], "retomar")

    def test_unvalidated_relation_is_flagged(self):  # §20.6
        g = self.guide()
        self.topic.curriculum.set([self.h3])  # h2 → h3 é "proposta"
        for ctx, d in (("Quadro", 6), ("Prova oral", 2)):
            self.obs(self.ana, self.h2, 1, d, context=ctx)
        self.obs(self.ana, self.h3, 1, 3, context="Lista")
        self.obs(self.ana, self.h3, 2, 1, context="Prova")
        rebuild_class(self.cg)
        first = self.steps(g, self.ana)["steps"][0]
        self.assertIn("a confirmar", first["reason"])

    def test_single_good_result_is_not_mastery(self):  # §20.14
        g = self.guide()
        self.obs(self.ana, self.h2, 4, 1, context="Exercício")
        rebuild_class(self.cg)
        step = [s for s in plan.preparation_plan(g, self.ana)["steps"] if s["topic"]][0]
        self.assertEqual(step["kind"], "estudar")
        self.assertEqual(step["state"], "ainda sem registro suficiente")

    def test_teacher_decision_changes_the_plan(self):  # §20.28
        g = self.guide()
        self.obs(self.ana, self.h2, 1, 3, context="Lista")
        self.obs(self.ana, self.h2, 2, 1, context="Prova")
        rebuild_class(self.cg)
        SkillJudgment.objects.create(school=self.school, student=self.ana, item=self.h2, state="consolidada",
                                     rationale="Demonstrou em sala, oralmente.", decided_by=self.prof)
        step = [s for s in self.steps(g, self.ana)["steps"] if s["topic"]][0]
        self.assertEqual(step["kind"], "revisar")

    def test_family_plan_follows_school_sharing_rule(self):
        g = self.guide()
        self.obs(self.ana, self.h2, 1, 3, context="Lista")
        self.obs(self.ana, self.h2, 2, 1, context="Prova")
        rebuild_class(self.cg)
        self.login(self.conta)
        page = self.client.get(reverse("study:detail", args=[g.pk]))
        self.assertContains(page, "A escola não ativou a personalização")
        scale = MasteryScale.for_school(self.school)
        scale.share_with_family = True
        scale.save()
        page = self.client.get(reverse("study:detail", args=[g.pk]))
        self.assertContains(page, "em desenvolvimento, com acompanhamento do professor")
        self.assertNotContains(page, "Dificuldade observada")

    def test_teacher_view_of_student_plan_is_scoped_and_audited(self):
        g = self.guide()
        self.login(self.prof)
        self.assertEqual(self.client.get(reverse("study:student_plan", args=[g.pk, self.ana.pk])).status_code, 200)
        for user in (self.prof_b, self.conta, self.fam):
            self.login(user)
            self.assertEqual(self.client.get(reverse("study:student_plan", args=[g.pk, self.ana.pk])).status_code, 403)


class ReuseTests(StudyBase):
    def test_reuse_copies_structure_to_own_class_as_draft(self):
        from apps.academics.models import TeacherAssignment

        TeacherAssignment.objects.create(school=self.school, school_year=self.cg_b.school_year, teacher=self.prof,
                                         class_group=self.cg_b, subject=self.mat)
        g = self.guide()
        StudyMaterial.objects.create(guide=g, topic=self.topic, kind="link", title="Página", url="https://a.org/x")
        StudyQuestion.objects.create(guide=g, student=self.ana, author=self.conta, text="dúvida da turma A")
        self.login(self.prof)
        r = self.client.post(reverse("study:reuse", args=[g.pk]), {"par": f"{self.cg_b.pk}-{self.mat.pk}"})
        self.assertEqual(r.status_code, 302)
        copy = ExamGuide.objects.exclude(pk=g.pk).get()
        self.assertEqual((copy.class_group, copy.status), (self.cg_b, ExamGuide.Status.DRAFT))
        self.assertEqual(copy.topics.count(), 1)
        self.assertEqual(copy.materials.get().topic, copy.topics.get())
        self.assertFalse(copy.questions.exists())
        r = self.client.post(reverse("study:reuse", args=[g.pk]), {"par": f"{self.cg_b.pk}-{self.geo.pk}"})
        self.assertEqual(ExamGuide.objects.count(), 2)  # par que não é dele: recusado


@override_settings(MEDIA_ROOT=MEDIA)
class LibraryTests(StudyBase):
    """P9-26: biblioteca da escola com busca, etiquetas, favoritos e reaproveitamento."""

    def setUp(self):
        super().setUp()
        self.g = self.guide()
        self.shared = StudyMaterial.objects.create(
            guide=self.g, kind="arquivo", title="Lista de frações", shared=True, tags="frações, revisão",
            file=SimpleUploadedFile("f.pdf", b"%PDF-1.4 f"), original_name="f.pdf", created_by=self.prof)
        self.shared.curriculum.add(self.h2)
        self.private = StudyMaterial.objects.create(guide=self.g, kind="link", title="Só da turma A",
                                                    url="https://a.org/1")

    def test_only_shared_and_only_pedagogical_staff(self):
        for user in (self.prof_b, self.coord, self.dir):
            self.login(user)
            page = self.client.get(reverse("study:library"))
            self.assertContains(page, "Lista de frações", msg_prefix=user.username)
            self.assertNotContains(page, "Só da turma A")
        for user in (self.sec, self.fam, self.conta):
            self.login(user)
            self.assertEqual(self.client.get(reverse("study:library")).status_code, 403)
            self.assertEqual(self.client.get(reverse("study:library_file", args=[self.shared.pk])).status_code, 403)

    def test_search_by_tag_and_skill_code_and_favorites(self):
        self.login(self.prof_b)
        self.assertContains(self.client.get(reverse("study:library"), {"q": "revisão"}), "Lista de frações")
        self.assertContains(self.client.get(reverse("study:library"), {"q": self.h2.code}), "Lista de frações")
        self.assertNotContains(self.client.get(reverse("study:library"), {"q": "geometria"}), "Lista de frações")
        self.client.post(reverse("study:library_favorite", args=[self.shared.pk]), {"next": "https://mal.example/"})
        self.assertContains(self.client.get(reverse("study:library"), {"favoritos": "1"}), "Lista de frações")

    def test_colleague_copies_into_own_guide_and_file_is_independent(self):
        from apps.academics.models import TeacherAssignment

        guide_b = ExamGuide.objects.create(school=self.school, class_group=self.cg_b, subject=self.mat,
                                           title="Prova B", exam_date=self.today + timedelta(days=5),
                                           created_by=self.prof_b)
        self.login(self.prof_b)
        r = self.client.post(reverse("study:library_use", args=[self.shared.pk]), {"prova": guide_b.pk})
        self.assertEqual(r.status_code, 302)
        copy = guide_b.materials.get()
        self.assertFalse(copy.shared)
        self.assertNotEqual(copy.file.name, self.shared.file.name)
        # Não pode usar numa prova que não é dele.
        r = self.client.post(reverse("study:library_use", args=[self.shared.pk]), {"prova": self.g.pk})
        self.assertEqual(r.status_code, 403)
        # Retirado na origem, sai da biblioteca.
        self.shared.removed_at = self.today
        StudyMaterial.objects.filter(pk=self.shared.pk).update(removed_at=timezone.now())
        self.assertNotContains(self.client.get(reverse("study:library")), "Lista de frações")
