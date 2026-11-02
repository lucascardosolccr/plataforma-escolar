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

class StaticCompressionAndCacheTests(TestCase):
    """Lighthouse (02/11/2026): estáticos sem compressão e sem cache no servidor da escola."""

    def test_css_and_js_are_gzipped_when_accepted(self):
        import gzip
        from pathlib import Path

        from django.conf import settings

        for path, ctype in (("css/ds-components.css", "text/css"), ("js/ds.js", "javascript"),
                            ("icons/sprite.svg", "image/svg+xml")):
            resp = self.client.get(f"/static/{path}", headers={"accept-encoding": "gzip, br"})
            self.assertEqual(resp["Content-Encoding"], "gzip", path)
            self.assertIn(ctype, resp["Content-Type"])
            self.assertIn("Accept-Encoding", resp["Vary"])
            original = (Path(settings.STATICFILES_DIRS[0]) / path).read_bytes()
            self.assertEqual(gzip.decompress(resp.content), original)
            self.assertLess(int(resp["Content-Length"]), len(original))
        plain = self.client.get("/static/css/ds-components.css")
        self.assertNotIn("Content-Encoding", plain)

    def test_cache_policy(self):
        resp = self.client.get("/static/vendor/bootstrap.min.css")
        self.assertEqual(resp["Cache-Control"], "public, max-age=604800")
        resp = self.client.get("/static/fonts/fraunces-latin-opsz-normal.woff2", headers={"accept-encoding": "gzip"})
        self.assertNotIn("Content-Encoding", resp)  # woff2 já é comprimido
        resp = self.client.get("/static/js/ds.js")
        self.assertEqual(resp["Cache-Control"], "no-cache")
        again = self.client.get("/static/js/ds.js", headers={"if-modified-since": resp["Last-Modified"]})
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again["Cache-Control"], "no-cache")

    def test_traversal_and_missing_files_still_refused(self):
        from django.test import Client

        client = Client(raise_request_exception=False)
        self.assertEqual(client.get("/static/../manage.py").status_code, 400)
        self.assertEqual(client.get("/static/%2e%2e/manage.py").status_code, 400)
        self.assertEqual(self.client.get("/static/css/nao-existe.css").status_code, 404)

    def test_html_pages_are_not_compressed(self):
        resp = self.client.get("/login/", headers={"accept-encoding": "gzip"})
        self.assertNotIn("Content-Encoding", resp)
