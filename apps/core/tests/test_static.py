from django.test import TestCase


class PublicStaticTests(TestCase):
    """Arquivos estáticos (Bootstrap/CSS/JS vendados) precisam ser públicos:
    a página de login é acessada por usuários anônimos e o LoginRequiredMiddleware
    redirecionaria qualquer rota não marcada como pública."""

    def test_anonymous_gets_css(self):
        for name in ("ds-tokens.css", "ds-components.css", "ds-shell.css"):
            resp = self.client.get(f"/static/css/{name}")
            self.assertEqual(resp.status_code, 200, name)

    def test_anonymous_gets_fonts_and_icons(self):
        """A tela de login (anônima) usa as fontes e os ícones locais."""
        for path in (
            "/static/fonts/atkinson-hyperlegible-next-latin-wght-normal.woff2",
            "/static/fonts/fraunces-latin-opsz-normal.woff2",
            "/static/icons/sprite.svg",
            "/static/js/ds.js",
        ):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_anonymous_gets_vendor_bootstrap(self):
        resp = self.client.get("/static/vendor/bootstrap.min.css")
        self.assertEqual(resp.status_code, 200)

    def test_anonymous_gets_theme_js(self):
        resp = self.client.get("/static/js/theme.js")
        self.assertEqual(resp.status_code, 200)

    def test_media_never_public(self):
        resp = self.client.get("/media/photos/fake.png")
        self.assertEqual(resp.status_code, 404)