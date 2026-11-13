"""Dossiê LGPD: o pacote de dados pessoais do estudante (acesso, art. 18 II; portabilidade, art. 18 V).

Complementa o inventário (``views_data_inventory``): o inventário conta o que existe; o dossiê
extrai os valores num arquivo JSON baixável. Mesmo gate da direção, porque reúne num só lugar
conteúdo que a secretaria e a administração não leem.
"""

import json

from django.urls import reverse

from apps.core.models import AuditLog
from apps.communication.tests.test_communication import CommunicationBase


class StudentDossierTests(CommunicationBase):
    def url(self):
        return reverse("student_dossier", args=[self.ana.pk])

    def test_only_direction_downloads_it(self):
        for user in (self.sec, self.admin, self.coord, self.prof, self.resp):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url()).status_code, 403, user.username)
        self.client.force_login(self.direc)
        self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_download_is_a_json_attachment_with_the_data(self):
        self.client.force_login(self.direc)
        resp = self.client.get(self.url())
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/json", resp["Content-Type"])
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertIn(".json", resp["Content-Disposition"])
        doc = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(doc["estudante"], self.ana.full_name)
        self.assertIn("art. 18", doc["finalidade"])
        self.assertEqual(doc["cadastro"]["nome"], "Ana")
        # O responsável vinculado aparece na seção de responsáveis.
        self.assertTrue(any(r["email"] == self.resp.email for r in doc["responsaveis"]))
        # A matrícula criada na base entra nos registros (introspecção do modelo).
        self.assertTrue(any(r["registro"] == "matrículas" for r in doc["registros"]))

    def test_dossier_export_is_audited(self):
        self.client.force_login(self.direc)
        self.client.get(self.url())
        self.assertTrue(
            AuditLog.objects.filter(action="export", detail__startswith="Exportou o dossiê").exists()
        )

    def test_no_internal_id_and_file_content_stays_out(self):
        self.client.force_login(self.direc)
        doc = json.loads(self.client.get(self.url()).content.decode("utf-8"))
        # O id interno do cadastro nunca sai; a foto (se houver) entra só pelo nome, não pelo binário.
        self.assertNotIn("id", doc["cadastro"])
        self.assertNotIn("ID", doc["cadastro"])

    def test_detail_page_shows_the_button_only_to_direction(self):
        detail = reverse("student_detail", args=[self.ana.pk])
        self.client.force_login(self.direc)
        self.assertContains(self.client.get(detail), "Baixar dossiê (LGPD)")
        self.client.force_login(self.sec)
        self.assertNotContains(self.client.get(detail), "Baixar dossiê (LGPD)")
