"""PWA: manifest, service worker e página offline.

Os três são públicos (o navegador os busca antes do login) e servidos do próprio domínio.
O service worker tem invariantes de LGPD que estes testes travam: nunca guardar páginas com
dados nem ``/media/``.
"""

import json

from django.test import TestCase
from django.urls import reverse


class PwaEndpointsTests(TestCase):
    def test_manifest_is_public_json_with_icons(self):
        resp = self.client.get(reverse("manifest"))  # sem login
        self.assertEqual(resp.status_code, 200)
        self.assertIn("manifest", resp["Content-Type"])
        data = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["start_url"], "/")
        self.assertEqual(len(data["icons"]), 2)
        self.assertTrue(all(i["type"] == "image/png" for i in data["icons"]))

    def test_service_worker_is_public_javascript(self):
        resp = self.client.get(reverse("service_worker"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("javascript", resp["Content-Type"])
        self.assertEqual(resp.request["PATH_INFO"], "/sw.js")  # precisa ficar na raiz p/ escopo "/"

    def test_service_worker_never_caches_pages_or_media(self):
        body = self.client.get(reverse("service_worker")).content.decode("utf-8")
        # Navegações (páginas com dados) vão pela rede; sem internet, caem na página offline.
        self.assertIn('req.mode === "navigate"', body)
        self.assertIn("/offline/", body)
        # Só /static/ é guardado; /media/ (fotos, documentos) nunca entra no cache.
        self.assertIn('url.pathname.startsWith("/static/")', body)
        self.assertNotIn("/media/", body.split("// /media/")[0])  # /media/ só aparece no comentário final

    def test_offline_page_is_public_and_self_contained(self):
        resp = self.client.get(reverse("offline"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Sem conexão")
        # Só carrega CSS do próprio servidor (CSP) — nada de origem externa.
        self.assertContains(resp, "css/ds-components.css")
        self.assertNotContains(resp, "http://")

    def test_login_page_wires_the_pwa(self):
        page = self.client.get(reverse("login"))
        self.assertContains(page, 'rel="manifest"')
        self.assertContains(page, "js/pwa.js")
