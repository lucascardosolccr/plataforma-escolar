from django.test import TestCase


class PublicStaticTests(TestCase):
    """Arquivos estáticos (Bootstrap/CSS/JS vendados) precisam ser públicos:
    a página de login é acessada por usuários anônimos e o LoginRequiredMiddleware
    redirecionaria qualquer rota não marcada como pública."""

    def test_anonymous_gets_css(self):
        resp = self.client.get("/static/css/app.css")
        self.assertEqual(resp.status_code, 200)

    def test_anonymous_gets_vendor_bootstrap(self):
        resp = self.client.get("/static/vendor/bootstrap.min.css")
        self.assertEqual(resp.status_code, 200)

    def test_anonymous_gets_theme_js(self):
        resp = self.client.get("/static/js/theme.js")
        self.assertEqual(resp.status_code, 200)

    def test_media_never_public(self):
        resp = self.client.get("/media/photos/fake.png")
        self.assertEqual(resp.status_code, 404)