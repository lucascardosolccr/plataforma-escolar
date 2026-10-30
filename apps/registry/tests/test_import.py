"""Importação de estudantes por planilha e fotos em lote (Prompt 14, rodada 2)."""

import io
import json
import shutil
import tempfile
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.academics.models import ClassGroup, SchoolYear
from apps.core.models import AuditLog, Role, School, User
from apps.registry import importer
from apps.registry.models import Enrollment, GuardianLink, ImportBatch, Student

PW = "Senha-forte-123"
HEADER = "Código do aluno;Nome;Sobrenome;Data de nascimento;Turma;Número de matrícula;Situação;Responsável;Telefone do responsável;Usuário do responsável"


def csv_file(*lines, name="alunos.csv"):
    body = "\n".join((HEADER,) + lines).encode("utf-8")
    return SimpleUploadedFile(name, body, content_type="text/csv")


def excel_like_xlsx(rows):
    """Planilha como o Excel grava: textos em sharedStrings e datas como número."""
    strings, sheet_rows = [], []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{chr(65 + c)}{r}"
            if isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}" s="1"><v>{value}</v></c>')
            else:
                strings.append(value)
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
        sheet_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Plan1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}>' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    return SimpleUploadedFile("alunos.xlsx", buf.getvalue())


class ImportBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        self.year = SchoolYear.objects.create(school=self.school, name="2026", is_current=True)
        self.turma_a = ClassGroup.objects.create(school=self.school, school_year=self.year, name="5º A")
        self.turma_b = ClassGroup.objects.create(school=self.school, school_year=self.year, name="5º B")
        self.sec = User.objects.create_user("sec", password=PW, role=Role.SECRETARIA, school=self.school)
        self.fam = User.objects.create_user("maria", password=PW, role=Role.RESPONSAVEL, school=self.school)
        self.client.login(username="sec", password=PW)

    def upload(self, f):
        resp = self.client.post(reverse("student_import"), {"file": f})
        self.assertEqual(resp.status_code, 302, getattr(resp, "context", {}) and resp.context.get("error"))
        return ImportBatch.objects.latest("pk")

    def rows(self, batch):
        return json.loads(batch.rows)


class TemplateTests(ImportBase):
    def test_template_has_instructions_and_round_trips(self):
        resp = self.client.get(reverse("student_import_template"))
        self.assertEqual(resp.status_code, 200)
        z = zipfile.ZipFile(io.BytesIO(resp.content))
        self.assertIn("Instruções", z.read("xl/workbook.xml").decode())
        # O próprio modelo, reenviado em branco, é lido sem erro de coluna.
        headers, rows, warnings = importer.read_table(SimpleUploadedFile("m.xlsx", resp.content))
        self.assertEqual(rows, [])
        self.assertEqual(warnings, [])


class ValidationTests(ImportBase):
    def test_preview_flags_each_problem_and_writes_nothing(self):
        Student.objects.create(school=self.school, first_name="Já", last_name="Existe", code="X1")
        batch = self.upload(csv_file(
            "1001;Ana;Souza;25/03/2016;5º A;M1;;Maria Souza;(11) 98888-7777;",
            "1002;;Sem Nome;01/01/2016;;;;;;",
            "1003;Bia;Data;31/02/2016;;;;;;",
            "1004;Caio;Turma;01/01/2016;9º Z;;;;;",
            "1001;Duda;Repetida;01/01/2016;;;;;;",
            "1005;Edu;Resp;01/01/2016;;;;João;;",
            "1006;Fê;Usuário;01/01/2016;;;;;;ninguem",
            "1007;Gabi;Futuro;01/01/2099;;;;;;",
            "1008;Hugo;Mat;01/01/2016;5º A;M1;;;;",
        ))
        res = {r["line"]: r for r in self.rows(batch)}
        self.assertEqual(res[2]["status"], "novo")
        self.assertIn("Nome em branco.", res[3]["errors"])
        self.assertTrue(any("inválida" in e for e in res[4]["errors"]))
        self.assertTrue(any("não existe" in e for e in res[5]["errors"]))
        self.assertTrue(any("Código repetido" in e for e in res[6]["errors"]))
        self.assertTrue(any("identificação suficiente" in e for e in res[7]["errors"]))
        self.assertTrue(any("não encontrado" in e for e in res[8]["errors"]))
        self.assertTrue(any("futuro" in e for e in res[9]["errors"]))
        self.assertTrue(any("matrícula repetido" in e for e in res[10]["errors"]))
        self.assertEqual(Student.objects.count(), 1)  # só o que já existia
        page = self.client.get(reverse("student_import_detail", args=[batch.pk]))
        self.assertContains(page, "Conferir a importação")

    def test_missing_required_column_is_refused(self):
        f = SimpleUploadedFile("x.csv", "Nome;Turma\nAna;5º A".encode(), content_type="text/csv")
        resp = self.client.post(reverse("student_import"), {"file": f})
        self.assertContains(resp, "Faltam colunas obrigatórias")
        self.assertFalse(ImportBatch.objects.exists())

    def test_not_a_spreadsheet_is_refused(self):
        f = SimpleUploadedFile("x.xlsx", b"isto nao e zip")
        self.assertContains(self.client.post(reverse("student_import"), {"file": f}), "não é uma planilha")

    def test_excel_shared_strings_and_numeric_dates(self):
        f = excel_like_xlsx([
            ["Código do aluno", "Nome *", "Sobrenome", "Data de nascimento *", "Turma"],
            [2026001, "Ana", "Souza", 42454, "5º A"],  # 42454 = 25/03/2016 no Excel (42370 = 01/01/2016)
        ])
        batch = self.upload(f)
        row = self.rows(batch)[0]
        self.assertEqual(row["status"], "novo", row["errors"])
        self.assertEqual(row["raw"]["codigo"], "2026001")
        self.assertEqual(importer.parse_date(row["raw"]["nascimento"]).isoformat(), "2016-03-25")


class ApplyTests(ImportBase):
    LINE = "1001;Ana;Souza;25/03/2016;5º A;M1;;Maria Souza;(11) 98888-7777;maria"

    def confirm(self, batch, **extra):
        data = {"action": "import", "mode": "novos"}
        data.update(extra)
        return self.client.post(reverse("student_import_confirm", args=[batch.pk]), data)

    def test_import_creates_student_enrollment_link_and_audit(self):
        batch = self.upload(csv_file(self.LINE, "1002;;x;01/01/2016;;;;;;"))
        self.confirm(batch)
        ana = Student.objects.get(code="1001")
        self.assertEqual(ana.guardian_contact_phone, "(11) 98888-7777")
        self.assertTrue(Enrollment.objects.filter(student=ana, class_group=self.turma_a, enrollment_number="M1").exists())
        self.assertTrue(GuardianLink.objects.filter(student=ana, guardian=self.fam, status="aprovado").exists())
        batch.refresh_from_db()
        self.assertEqual((batch.status, batch.created_count, batch.error_count), ("concluida", 1, 1))
        self.assertTrue(AuditLog.objects.filter(target_type="ImportBatch", detail__contains="1 cadastrados").exists())
        rejected = self.client.get(reverse("student_import_rejected", args=[batch.pk]))
        self.assertIn(b"Nome em branco", zipfile.ZipFile(io.BytesIO(rejected.content)).read("xl/worksheets/sheet1.xml"))

    def test_resending_the_same_file_does_not_duplicate(self):
        self.confirm(self.upload(csv_file(self.LINE)))
        again = self.upload(csv_file(self.LINE))
        self.assertEqual(self.rows(again)[0]["status"], "igual")
        self.confirm(again)
        self.assertEqual(Student.objects.count(), 1)
        self.assertEqual(Enrollment.objects.count(), 1)
        # Sem código, reconhecido por nome + nascimento exatos.
        no_code = self.upload(csv_file(";Ana;Souza;25/03/2016;;;;;;"))
        self.assertEqual(self.rows(no_code)[0]["status"], "igual")

    def test_updates_need_update_mode_and_explicit_confirmation(self):
        self.confirm(self.upload(csv_file(self.LINE)))
        batch = self.upload(csv_file("1001;Ana;Souza Lima;25/03/2016;;;;;;"))
        row = self.rows(batch)[0]
        self.assertEqual(row["status"], "alterar")
        self.assertEqual(row["changes"][0]["new"], "Souza Lima")
        # Modo "atualizar" sem marcar a confirmação: recusado, nada muda.
        self.confirm(batch, mode="atualizar")
        self.assertEqual(Student.objects.get(code="1001").last_name, "Souza")
        # Modo "só novos": a alteração é ignorada.
        self.confirm(batch, mode="novos")
        self.assertEqual(Student.objects.get(code="1001").last_name, "Souza")
        batch2 = self.upload(csv_file("1001;Ana;Souza Lima;25/03/2016;;;;;;"))
        self.confirm(batch2, mode="atualizar", confirm_updates="1")
        ana = Student.objects.get(code="1001")
        self.assertEqual(ana.last_name, "Souza Lima")
        self.assertEqual(ana.guardian_contact_phone, "(11) 98888-7777")  # célula vazia não apagou

    def test_active_enrollment_elsewhere_is_not_silently_moved(self):
        self.confirm(self.upload(csv_file(self.LINE)))
        batch = self.upload(csv_file("1001;Ana;Souza;25/03/2016;5º B;;;;;"))
        self.assertTrue(any("Transferir" in e for e in self.rows(batch)[0]["errors"]))

    def test_cancel_writes_nothing(self):
        batch = self.upload(csv_file(self.LINE))
        self.client.post(reverse("student_import_confirm", args=[batch.pk]), {"action": "cancel"})
        batch.refresh_from_db()
        self.assertEqual(batch.status, "cancelada")
        self.assertFalse(Student.objects.exists())

    def test_cannot_confirm_twice(self):
        batch = self.upload(csv_file(self.LINE))
        self.confirm(batch)
        self.confirm(batch)
        self.assertEqual(Student.objects.count(), 1)


class ImportPermissionTests(ImportBase):
    def test_only_secretaria_and_admin(self):
        for role in (Role.PROFESSOR, Role.RESPONSAVEL, Role.COORDENACAO, Role.DIRECAO, Role.ESTUDANTE):
            User.objects.create_user(f"u-{role}", password=PW, role=role, school=self.school)
            self.client.logout()
            self.client.login(username=f"u-{role}", password=PW)
            for name in ("student_import", "student_import_template", "student_photo_batch"):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403, (role, name))

    def test_batch_of_another_school_is_hidden(self):
        other = School.objects.create(name="Outra", code="o")
        batch = ImportBatch.objects.create(school=other, filename="x.csv", rows="[]")
        self.assertEqual(self.client.get(reverse("student_import_detail", args=[batch.pk])).status_code, 404)


def png_bytes(size=(800, 600), exif_gps=False):
    from PIL import Image

    img = Image.new("RGB", size, (200, 30, 30))
    buf = io.BytesIO()
    if exif_gps:
        exif = Image.Exif()
        exif[0x8825] = {1: "S", 2: (23.0, 33.0, 0.0)}  # GPSInfo
        img.save(buf, "JPEG", exif=exif)
    else:
        img.save(buf, "PNG")
    return buf.getvalue()


class PhotoBatchTests(ImportBase):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)

    def test_photos_match_only_by_exact_code_and_lose_gps(self):
        from PIL import Image

        with override_settings(MEDIA_ROOT=self.media):
            ana = Student.objects.create(school=self.school, first_name="Ana", code="2026001")
            Student.objects.create(school=self.school, first_name="Bia")
            files = [
                SimpleUploadedFile("2026001.jpg", png_bytes(exif_gps=True)),
                SimpleUploadedFile("Bia.png", png_bytes()),  # nome do aluno: nunca associa
                SimpleUploadedFile("2026999.png", png_bytes()),
            ]
            resp = self.client.post(reverse("student_photo_batch"), {"photos": files})
            self.assertContains(resp, "1 associada")
            ana.refresh_from_db()
            self.assertTrue(ana.photo)
            with Image.open(ana.photo.path) as img:
                self.assertEqual(img.size, (512, 512))
                self.assertNotIn(0x8825, img.getexif())
            self.assertFalse(Student.objects.get(first_name="Bia").photo)

    def test_fake_image_is_refused(self):
        with override_settings(MEDIA_ROOT=self.media):
            Student.objects.create(school=self.school, first_name="Ana", code="A1")
            resp = self.client.post(reverse("student_photo_batch"),
                                    {"photos": [SimpleUploadedFile("A1.jpg", b"MZ nao sou imagem")]})
            self.assertContains(resp, "não é uma imagem válida")
