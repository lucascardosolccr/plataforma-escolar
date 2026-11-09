"""Nenhum recurso de terceiros nas páginas, e alertas com a cor certa.

A base carregava fontes do Google, ícones do jsDelivr e animações do cdnjs:
cada página aberta por uma família entregava o IP dela a três empresas, e a
plataforma ficava sem ícones numa rede sem internet — embora a documentação
afirmasse que tudo era local.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Role, School, User

TEMPLATES_DIR = Path(settings.BASE_DIR) / "templates"
STATIC_DIR = Path(settings.BASE_DIR) / "static"
# Atributo src/href (ou url() de CSS) apontando para outro host.
EXTERNAL = re.compile(
    r"""(?:src|href)\s*=\s*["']\s*(?:https?:)?//|@import\s+url\(\s*["']?(?:https?:)?//"""
    r"""|url\(\s*["']?https?://""",
    re.IGNORECASE,
)


class NoExternalAssetsTests(TestCase):
    def test_templates_reference_no_external_host(self):
        culpados = []
        for path in TEMPLATES_DIR.rglob("*.html"):
            for n, linha in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if EXTERNAL.search(linha):
                    culpados.append(f"{path.relative_to(TEMPLATES_DIR)}:{n}")
        self.assertEqual(culpados, [], "Recurso externo em template")

    def test_no_multiline_hash_comment_in_templates(self):
        """``{# #}`` só vale numa linha: com quebra, o texto sai impresso na
        página. Comentário longo usa ``{% comment %}``."""
        culpados = []
        for path in TEMPLATES_DIR.rglob("*.html"):
            for n, linha in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "{#" in linha and "#}" not in linha.split("{#", 1)[1]:
                    culpados.append(f"{path.relative_to(TEMPLATES_DIR)}:{n}")
        self.assertEqual(culpados, [])

    def test_css_variables_used_in_templates_are_defined(self):
        """Variável CSS usada num template precisa existir no design system.

        Avatares usavam var(--brand-1) do app.css removido e ficaram com as
        iniciais brancas sobre fundo vazio, sem nenhum erro aparente."""
        definidas = set()
        for css in STATIC_DIR.glob("css/*.css"):
            definidas |= set(re.findall(r"(--[a-z0-9-]+)\s*:", css.read_text(encoding="utf-8-sig")))
        faltando = []
        for path in TEMPLATES_DIR.rglob("*.html"):
            texto = path.read_text(encoding="utf-8")
            definidas_aqui = set(re.findall(r"(--[a-z0-9-]+)\s*:", texto))
            for nome in re.findall(r"var\((--(?:ds|brand|avatar|kind)[a-z0-9-]*)", texto):
                if nome not in definidas and nome not in definidas_aqui:
                    faltando.append(f"{path.relative_to(TEMPLATES_DIR)}: {nome}")
        self.assertEqual(faltando, [])

    def test_own_css_and_js_reference_no_external_host(self):
        culpados = []
        for path in list(STATIC_DIR.glob("css/*.css")) + list(STATIC_DIR.glob("js/*.js")):
            texto = path.read_text(encoding="utf-8-sig")
            if EXTERNAL.search(texto):
                culpados.append(path.name)
        self.assertEqual(culpados, [])

    def test_csp_blocks_third_party_origins(self):
        resp = self.client.get(reverse("login"))
        csp = resp.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn("http", csp)

    def test_authenticated_page_also_has_csp(self):
        school = School.objects.create(name="Escola", code="e")
        User.objects.create_user(
            username="sec", password="senha-forte-1", role=Role.SECRETARIA, school=school
        )
        self.client.login(username="sec", password="senha-forte-1")
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("default-src 'self'", resp.headers["Content-Security-Policy"])
        # Só a câmera (portaria), só da própria plataforma; microfone e localização desligados.
        self.assertIn("camera=(self)", resp.headers["Permissions-Policy"])
        self.assertIn("microphone=()", resp.headers["Permissions-Policy"])
        self.assertIn("geolocation=()", resp.headers["Permissions-Policy"])
        self.assertNotContains(resp, "googleapis")
        self.assertNotContains(resp, "gsap")

    def test_logged_in_pages_are_not_kept_by_the_browser(self):
        # Computador compartilhado: depois de "Sair", o "Voltar" do navegador não pode reexibir dados de estudantes.
        school = School.objects.create(name="Escola", code="e")
        User.objects.create_user(username="sec", password="senha-forte-1", role=Role.SECRETARIA, school=school)
        self.client.login(username="sec", password="senha-forte-1")
        cc = self.client.get(reverse("home")).headers["Cache-Control"]
        self.assertIn("no-store", cc)
        self.assertIn("private", cc)
        self.assertIn("no-store", self.client.get(reverse("student_list")).headers["Cache-Control"])


class MessageColorTests(TestCase):
    """Sucesso aparecia amarelo e aviso aparecia vermelho (mapa deslocado)."""

    def setUp(self):
        school = School.objects.create(name="Escola", code="e")
        User.objects.create_user(
            username="sec", password="senha-forte-1", role=Role.SECRETARIA, school=school
        )
        self.client.login(username="sec", password="senha-forte-1")

    def test_success_message_is_green(self):
        resp = self.client.post(
            reverse("communication:notification_read_all"), follow=True
        )
        self.assertContains(resp, "alert-success")
        self.assertNotContains(resp, "alert-warning")

    def test_tag_map_follows_django_levels(self):
        from django.contrib.messages import constants

        tags = settings.MESSAGE_TAGS
        self.assertEqual(tags[constants.SUCCESS], "success")
        self.assertEqual(tags[constants.WARNING], "warning")
        self.assertEqual(tags[constants.ERROR], "danger")
        self.assertEqual(tags[constants.INFO], "info")
