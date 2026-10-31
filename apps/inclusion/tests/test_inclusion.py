"""Necessidades específicas, laudos, plano individualizado, permissões e privacidade (Prompt 15, seções 4 e 5)."""

import io
import shutil
import tempfile
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.communication.models import Notification
from apps.coordination.models import CoordinatorAssignment
from apps.core.models import AuditLog, Role, School, User
from apps.inclusion.models import (SupportCase, SupportCategory, SupportDocument, SupportEvent, SupportNeed,
                                   SupportPlan, SupportPlanVersion, SupportRequest, SupportSettings)
from apps.inclusion.services import discard_candidates
from apps.registry.models import Enrollment, GuardianLink, Student

PW = "Senha-forte-123"
MEDIA = tempfile.mkdtemp(prefix="inclusao-testes-")
PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


def pdf(name="laudo.pdf", data=PDF):
    return SimpleUploadedFile(name, data, content_type="application/pdf")


@override_settings(MEDIA_ROOT=MEDIA)
class Base(TestCase):
    coordenacao_restrita = True

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        year = SchoolYear.objects.create(school=self.school, name="2026", is_current=True)
        self.a = ClassGroup.objects.create(school=self.school, school_year=year, name="6º Ano A")
        self.b = ClassGroup.objects.create(school=self.school, school_year=year, name="6º Ano B")
        mat = Subject.objects.create(school=self.school, name="Matemática")
        mk = lambda u, r, s=None: User.objects.create_user(u, password=PW, role=r, school=s or self.school,
                                                            first_name=u.title())
        self.fam, self.fam2 = mk("fam", Role.RESPONSAVEL), mk("fam2", Role.RESPONSAVEL)
        self.prof, self.prof_b = mk("prof", Role.PROFESSOR), mk("profb", Role.PROFESSOR)
        self.coord, self.coord_b = mk("coord", Role.COORDENACAO), mk("coordb", Role.COORDENACAO)
        self.dir, self.sec, self.adm = mk("dir", Role.DIRECAO), mk("sec", Role.SECRETARIA), mk("adm", Role.ADMIN)
        TeacherAssignment.objects.create(school=self.school, school_year=year, teacher=self.prof, class_group=self.a,
                                         subject=mat)
        TeacherAssignment.objects.create(school=self.school, school_year=year, teacher=self.prof_b,
                                         class_group=self.b, subject=mat)
        for c, cg in ((self.coord, self.a), (self.coord_b, self.b)):
            CoordinatorAssignment.objects.create(school=self.school, coordinator=c,
                                                 starts_on=timezone.localdate()).class_groups.add(cg)
        self.ana = Student.objects.create(school=self.school, first_name="Ana", last_name="Lima")
        self.bia = Student.objects.create(school=self.school, first_name="Bia")
        self.aluna = mk("ana.aluna", Role.ESTUDANTE)
        self.ana.user = self.aluna
        self.ana.save()
        Enrollment.objects.create(school=self.school, student=self.ana, class_group=self.a, school_year=year)
        Enrollment.objects.create(school=self.school, student=self.bia, class_group=self.b, school_year=year)
        GuardianLink.objects.create(school=self.school, guardian=self.fam, student=self.ana, status="aprovado")
        GuardianLink.objects.create(school=self.school, guardian=self.fam2, student=self.bia, status="aprovado")
        self.tea = SupportCategory.ensure_defaults(self.school).get(name__startswith="Transtorno do Espectro")

    def login(self, user):
        self.client.logout()
        self.client.login(username=user.username, password=PW)

    def declare(self, **extra):
        self.login(self.fam)
        data = {"has_report": "sim", "declared_categories": [self.tea.pk], "family_notes": "Prefere avisos com antecedência.",
                "understood": "on", "kind": "laudo", "issuer": "CAPS Infantil"}
        data.update(extra)
        return self.client.post(reverse("inclusion:declare", args=[self.ana.pk]), data)

    def case(self):
        return SupportCase.objects.get(student=self.ana)


class FamilyFlowTests(Base):
    def test_declare_with_document(self):
        r = self.declare(file=pdf())
        self.assertEqual(r.status_code, 302)
        case = self.case()
        self.assertEqual(case.status, "aguardando")
        self.assertEqual(list(case.declared_categories.all()), [self.tea])
        doc = case.documents.get()
        self.assertEqual((doc.source, doc.status, doc.issuer, len(doc.sha256)), ("familia", "aguardando",
                                                                                   "CAPS Infantil", 64))
        self.assertNotIn("Ana", doc.file.name)  # nome imprevisível, sem dado do estudante
        # Enviar não valida nada.
        self.assertFalse(case.validated_categories.exists())
        # Equipe que alcança o estudante é avisada, sem diagnóstico no texto.
        n = Notification.objects.get(user=self.coord, kind="apoio")
        self.assertNotIn("Autista", n.title + n.body)
        self.assertFalse(Notification.objects.filter(user=self.coord_b).exists())
        self.assertTrue(Notification.objects.filter(user=self.dir, kind="apoio").exists())
        self.assertFalse(Notification.objects.filter(user=self.prof, kind="apoio").exists())
        self.assertTrue(AuditLog.objects.filter(user=self.fam, target_type="SupportDocument", action="create").exists())

    def test_purpose_notice_and_understanding_required(self):
        self.login(self.fam)
        r = self.client.get(reverse("inclusion:declare", args=[self.ana.pk]))
        self.assertContains(r, "Não é obrigatório ter laudo")
        self.assertContains(r, "nunca o laudo nem o diagnóstico")
        r = self.declare(understood="")
        self.assertEqual(r.status_code, 200)
        self.assertIn("understood", r.context["form"].errors)

    def test_file_validation(self):
        SupportSettings.objects.create(school=self.school, max_upload_mb=1)
        url = reverse("inclusion:document_upload", args=[self.ana.pk])
        self.login(self.fam)
        cases = {
            "exe renomeado": SimpleUploadedFile("laudo.pdf", b"MZ\x90\x00binario"),
            "extensão": SimpleUploadedFile("laudo.docx", b"PK\x03\x04..."),
            "grande": pdf(data=PDF + b"0" * (1024 * 1024)),
            "script no pdf": pdf(data=b"%PDF-1.4\n<< /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >>\n"),
            "vazio": SimpleUploadedFile("laudo.pdf", b""),
            "imagem falsa": SimpleUploadedFile("laudo.png", b"\x89PNG\r\n\x1a\nnao e imagem"),
        }
        for label, f in cases.items():
            with self.subTest(label):
                r = self.client.post(url, {"file": f, "kind": "laudo"})
                self.assertEqual(r.status_code, 200)
                self.assertIn("file", r.context["form"].errors)
        self.assertFalse(SupportDocument.objects.exists())

    def test_image_is_reencoded_without_exif(self):
        buf = io.BytesIO()
        img = Image.new("RGB", (40, 30), "white")
        exif = Image.Exif()
        exif[0x010F] = "Fabricante"  # Make
        img.save(buf, format="JPEG", exif=exif.tobytes())
        self.login(self.fam)
        r = self.client.post(reverse("inclusion:document_upload", args=[self.ana.pk]),
                             {"file": SimpleUploadedFile("foto.jpg", buf.getvalue()), "kind": "laudo"})
        self.assertEqual(r.status_code, 302)
        doc = SupportDocument.objects.get()
        with doc.file.open("rb") as fh:
            self.assertFalse(dict(Image.open(fh).getexif()))

    def test_replace_keeps_previous(self):
        self.declare(file=pdf())
        old = SupportDocument.objects.get()
        self.client.post(reverse("inclusion:document_upload", args=[self.ana.pk]) + f"?substitui={old.public_id}",
                         {"file": pdf("laudo-2026.pdf"), "kind": "laudo"})
        old.refresh_from_db()
        new = SupportDocument.objects.exclude(pk=old.pk).get()
        self.assertEqual((old.status, new.replaces), ("substituido", old))
        self.assertTrue(old.available)  # continua guardado
        self.assertGreaterEqual(SupportEvent.objects.filter(case=self.case()).count(), 3)

    def test_complementation_round_trip(self):
        self.declare()
        self.login(self.coord)
        self.client.post(reverse("inclusion:request_create", args=[self.ana.pk]),
                         {"message": "Enviar relatório atualizado da fonoaudióloga."})
        case = self.case()
        self.assertEqual(case.status, "complementacao")
        self.assertTrue(Notification.objects.filter(user=self.fam, kind="apoio", title__contains="complementação").exists())
        req = SupportRequest.objects.get()
        self.login(self.fam)
        r = self.client.get(reverse("inclusion:case_detail", args=[self.ana.pk]))
        self.assertContains(r, "Enviar relatório atualizado")
        self.client.post(reverse("inclusion:request_respond", args=[req.pk]),
                         {"response": "Segue o relatório.", "file": pdf("relatorio.pdf"), "kind": "laudo"})
        req.refresh_from_db()
        self.assertEqual((req.status, self.case().status), ("respondida", "aguardando"))
        self.assertEqual(SupportDocument.objects.count(), 1)
        # Segundo envio não sobrescreve a resposta.
        self.client.post(reverse("inclusion:request_respond", args=[req.pk]), {"response": "outra"})
        req.refresh_from_db()
        self.assertEqual(req.response, "Segue o relatório.")


class TeamFlowTests(Base):
    def test_analysis_and_validation(self):
        self.declare(file=pdf())
        doc = SupportDocument.objects.get()
        self.login(self.coord)
        self.client.post(reverse("inclusion:document_review", args=[doc.public_id]),
                         {"decision": "analisado", "note": "Conferido em reunião."})
        doc.refresh_from_db()
        self.assertEqual((doc.status, doc.reviewed_by), ("analisado", self.coord))
        self.assertTrue(Notification.objects.filter(user=self.fam, title__contains="analisada").exists())
        url = reverse("inclusion:case_analysis", args=[self.ana.pk])
        r = self.client.post(url, {"validated_categories": [self.tea.pk], "validation_basis": "",
                                   "legal_basis": "politica_publica", "status": "analisado"})
        self.assertIn("validation_basis", r.context["form"].errors)
        self.client.post(url, {"validated_categories": [self.tea.pk], "validation_basis": "Estudo de caso de 10/10.",
                               "legal_basis": "politica_publica", "status": "analisado", "note": "Registro concluído."})
        case = self.case()
        self.assertEqual((list(case.validated_categories.all()), case.validated_by), ([self.tea], self.coord))

    def test_need_without_report(self):
        self.login(self.coord)
        r = self.client.post(reverse("inclusion:need_create", args=[self.ana.pk]), {
            "area": "aprendizagem", "description": "Leitura lenta de enunciados longos.",
            "resources": "Prova com fonte ampliada.", "classroom_strategies": "Ler o enunciado em voz alta.",
            "care_notes": "", "share_with_teachers": "on", "active": "on"})
        self.assertEqual(r.status_code, 302)
        case = self.case()
        self.assertEqual((case.has_report, case.status), ("", "atualizado"))
        self.assertEqual(SupportNeed.objects.count(), 1)

    def test_plan_versions_rules_and_family_view(self):
        self.declare()
        self.login(self.coord)
        url = reverse("inclusion:plan_create", args=[self.ana.pk])
        today = timezone.localdate()
        base = {"status": "vigente", "starts_on": today.isoformat(),
                "review_due": (today + timedelta(days=400)).isoformat(), "objectives": "Ler com autonomia.",
                "strategies": "Leitura compartilhada.", "teacher_summary": "Dar mais tempo nas provas.",
                "context_analysis": "Sala barulhenta no turno da tarde.", "responsibles": [self.prof.pk]}
        r = self.client.post(url, base)
        self.assertIn("review_due", r.context["form"].errors)  # mais de um ano
        r = self.client.post(url, {**base, "review_due": (today + timedelta(days=180)).isoformat(),
                                   "objectives": "", "strategies": "", "curricular_measures": ""})
        self.assertIn("status", r.context["form"].errors)  # vigente sem objetivos
        self.client.post(url, {**base, "review_due": (today + timedelta(days=180)).isoformat()})
        plan = SupportPlan.objects.get()
        self.assertEqual((plan.status, plan.version), ("vigente", 1))
        self.assertTrue(Notification.objects.filter(user=self.fam, title__contains="Plano individualizado").exists())
        self.client.post(reverse("inclusion:plan_edit", args=[self.ana.pk, plan.pk]),
                         {**base, "review_due": (today + timedelta(days=180)).isoformat(),
                          "objectives": "Ler e interpretar com autonomia."})
        plan.refresh_from_db()
        self.assertEqual(plan.version, 2)
        self.assertEqual(SupportPlanVersion.objects.get().data["objectives"], "Ler com autonomia.")
        for kind, notes in (("evolucao", "Leu sozinho o texto curto."), ("devolutiva", "Reunião com a mãe em 12/11.")):
            self.client.post(reverse("inclusion:plan_review", args=[self.ana.pk, plan.pk]),
                             {"kind": kind, "happened_on": today.isoformat(), "notes": notes})
        self.login(self.fam)
        r = self.client.get(reverse("inclusion:case_detail", args=[self.ana.pk]))
        self.assertContains(r, "Ler e interpretar com autonomia.")
        self.assertContains(r, "Reunião com a mãe em 12/11.")
        self.assertNotContains(r, "Leu sozinho o texto curto.")  # registro interno de evolução


class GuidanceTests(Base):
    def setUp(self):
        super().setUp()
        self.declare(file=pdf())
        case = self.case()
        SupportNeed.objects.create(case=case, area="visual", description="Baixa visão.", resources="Fonte 18.",
                                   classroom_strategies="Sentar perto do quadro.", share_with_teachers=True)
        SupportNeed.objects.create(case=case, area="cuidados", description="Interno.", care_notes="SÓ EQUIPE",
                                   share_with_teachers=False)

    def test_teacher_sees_strategies_not_diagnosis(self):
        self.login(self.prof)
        r = self.client.get(reverse("inclusion:guidance"))
        self.assertContains(r, "Sentar perto do quadro.")
        self.assertContains(r, "Fonte 18.")
        for hidden in ("Transtorno do Espectro", "Prefere avisos", "laudo.pdf", "SÓ EQUIPE", "Baixa visão."):
            self.assertNotContains(r, hidden)
        self.assertTrue(AuditLog.objects.filter(user=self.prof, action="view", target_type="SupportGuidance").exists())
        # Professor de outra turma não vê a Ana.
        self.login(self.prof_b)
        self.assertNotContains(self.client.get(reverse("inclusion:guidance")), "Sentar perto do quadro.")

    def test_activity_points_to_guidance(self):
        from apps.pedagogy.models import Activity

        act = Activity.objects.create(school=self.school, class_group=self.a, subject=Subject.objects.get(),
                                      title="Mapa", class_date=timezone.localdate(), created_by=self.prof)
        self.login(self.prof)
        r = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        self.assertContains(r, "1 estudante desta turma tem orientação de apoio")


class AccessTests(Base):
    def setUp(self):
        super().setUp()
        self.declare(file=pdf())
        self.doc = SupportDocument.objects.get()
        self.case_url = reverse("inclusion:case_detail", args=[self.ana.pk])
        self.doc_url = reverse("inclusion:document_download", args=[self.doc.public_id])

    def test_who_opens_the_case_and_the_document(self):
        allowed = (self.fam, self.coord, self.dir)
        denied = (self.fam2, self.prof, self.prof_b, self.coord_b, self.sec, self.adm, self.aluna)
        for user in allowed:
            self.login(user)
            with self.subTest(user=user.username):
                self.assertEqual(self.client.get(self.case_url).status_code, 200)
                r = self.client.get(self.doc_url)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r["Cache-Control"], "no-store, private")
                self.assertIn("attachment", r["Content-Disposition"])
        for user in denied:
            self.login(user)
            with self.subTest(user=user.username):
                self.assertEqual(self.client.get(self.case_url).status_code, 403)
                self.assertEqual(self.client.get(self.doc_url).status_code, 403)
        self.assertEqual(AuditLog.objects.filter(action="download", target_type="SupportDocument").count(), 3)
        self.assertTrue(AuditLog.objects.filter(action="view", user=self.coord, target_type="SupportCase").exists())

    def test_guardian_cannot_act_on_other_child(self):
        self.login(self.fam2)
        for name in ("declare", "document_upload"):
            self.assertEqual(self.client.get(reverse(f"inclusion:{name}", args=[self.ana.pk])).status_code, 403)
        req = SupportRequest.objects.create(case=self.case(), message="x", requested_by=self.coord)
        self.assertEqual(self.client.post(reverse("inclusion:request_respond", args=[req.pk]),
                                          {"response": "invasão"}).status_code, 403)

    def test_unpredictable_and_scoped_urls(self):
        import uuid

        self.login(self.fam)
        self.assertEqual(self.client.get(reverse("inclusion:document_download", args=[uuid.uuid4()])).status_code, 404)
        self.assertEqual(self.client.get(f"/apoio/documento/{self.doc.pk}/").status_code, 404)
        other = School.objects.create(name="Outra", code="o")
        intruder = User.objects.create_user("dir2", password=PW, role=Role.DIRECAO, school=other)
        self.login(intruder)
        self.assertEqual(self.client.get(self.doc_url).status_code, 404)
        self.assertEqual(self.client.get(self.case_url).status_code, 404)
        # Mídia não é servida por URL pública.
        self.assertEqual(self.client.get("/media/" + self.doc.file.name).status_code, 404)

    def test_secretaria_sees_status_only(self):
        self.login(self.sec)
        r = self.client.get(reverse("inclusion:overview"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Ana")
        self.assertNotContains(r, "Prefere avisos")
        r = self.client.post(reverse("inclusion:document_upload", args=[self.ana.pk]),
                             {"file": pdf("entregue.pdf"), "kind": "relatorio_escolar"})
        self.assertEqual(r.status_code, 302)
        received = SupportDocument.objects.get(original_name="entregue.pdf")
        self.assertEqual((received.source, received.status), ("escola", "recebido"))
        self.assertEqual(self.client.get(reverse("inclusion:document_download",
                                                 args=[received.public_id])).status_code, 403)
        for name in ("request_create", "case_analysis", "need_create", "plan_create"):
            self.assertEqual(self.client.get(reverse(f"inclusion:{name}", args=[self.ana.pk])).status_code, 403)

    def test_reports_do_not_carry_sensitive_data(self):
        self.login(self.dir)
        for slug in ("acompanhamento", "dificuldades", "pendencias_documentais", "boletim"):
            r = self.client.get(reverse("analytics:report_csv", args=[slug]))
            if r.status_code == 200:
                body = b"".join(r.streaming_content) if r.streaming else r.content
                self.assertNotIn("Espectro".encode(), body)
                self.assertNotIn(b"laudo.pdf", body)


class RetentionAndPanelTests(Base):
    def test_discard_only_after_retention(self):
        self.declare(file=pdf())
        doc = SupportDocument.objects.get()
        self.assertEqual(discard_candidates(self.school), [])  # estudante ativo
        Enrollment.objects.filter(student=self.ana).update(status="concluido", ended_on=date.today() - timedelta(days=6 * 365))
        self.assertEqual(discard_candidates(self.school), [doc])
        self.login(self.coord)
        self.assertEqual(self.client.get(reverse("inclusion:retention")).status_code, 403)
        self.login(self.dir)
        path = doc.file.path
        self.client.post(reverse("inclusion:retention"), {"ids": [str(doc.public_id)]})
        doc.refresh_from_db()
        import os

        self.assertEqual((doc.status, bool(doc.file), os.path.exists(path)), ("descartado", False, False))
        self.assertEqual(len(doc.sha256), 64)  # o registro permanece
        self.assertTrue(AuditLog.objects.filter(action="delete", target_type="SupportDocument").exists())

    def test_panel_aggregates_without_diagnosis(self):
        case = SupportCase.objects.create(school=self.school, student=self.ana)
        SupportNeed.objects.create(case=case, area="visual", description="x")
        self.login(self.dir)
        r = self.client.get(reverse("inclusion:panel"))
        self.assertContains(r, "menos de 5")
        self.assertNotContains(r, "Ana")
        self.assertNotContains(r, "Espectro")
        self.login(self.prof)
        self.assertEqual(self.client.get(reverse("inclusion:panel")).status_code, 403)
