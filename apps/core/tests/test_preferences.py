"""Favoritos e filtros salvos na conta (antes ficavam só no navegador)."""

import json

from django.test import TestCase
from django.urls import reverse

from apps.core.models import Role, School, User, UserPreference

PW = "senha-forte-1"


class PreferenceTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        self.prof = User.objects.create_user(username="prof", password=PW, role=Role.PROFESSOR.value,
                                             school=self.school)
        self.coord = User.objects.create_user(username="coord", password=PW, role=Role.COORDENACAO.value,
                                              school=self.school)
        self.url = reverse("save_preferences")

    def post(self, data, user="prof"):
        self.client.login(username=user, password=PW)
        return self.client.post(self.url, json.dumps(data), content_type="application/json")

    def test_saves_and_page_carries_them(self):
        r = self.post({"favorites": ["calendar", "calendar", "home"],
                       "filters": [{"url": "/atividades/?turma=1&status=publicada", "label": "Atividades  · 5º A"}]})
        self.assertEqual(r.status_code, 200)
        pref = UserPreference.objects.get(user=self.prof)
        self.assertEqual(pref.favorites, ["calendar", "home"])
        self.assertEqual(pref.saved_filters, [{"url": "/atividades/?turma=1&status=publicada",
                                               "label": "Atividades · 5º A"}])
        page = self.client.get(reverse("home"))
        self.assertContains(page, 'id="ds-prefs"')
        self.assertEqual(page.context["user_prefs"]["favorites"], ["calendar", "home"])
        # Só a lista enviada muda; a outra fica.
        self.post({"favorites": []})
        pref.refresh_from_db()
        self.assertEqual(pref.favorites, [])
        self.assertEqual(len(pref.saved_filters), 1)

    def test_rejects_external_unknown_or_filterless_urls(self):
        bad = [{"url": u, "label": "x"} for u in (
            "https://evil.example/?a=1", "//evil.example/?a=1", "/atividades/", "/nao-existe/?a=1",
            "javascript:alert(1)", "/\\evil.example/?a=1")]
        self.post({"filters": bad + ["texto", {"url": 5, "label": "x"}], "favorites": ["<script>", "a" * 61, 3]})
        pref = UserPreference.objects.get(user=self.prof)
        self.assertEqual(pref.saved_filters, [])
        self.assertEqual(pref.favorites, [])

    def test_limits_and_isolation_between_accounts(self):
        self.post({"filters": [{"url": f"/atividades/?p={i}", "label": str(i)} for i in range(15)],
                   "favorites": [f"k{i}" for i in range(12)]})
        pref = UserPreference.objects.get(user=self.prof)
        self.assertEqual(len(pref.saved_filters), 10)
        self.assertEqual(len(pref.favorites), 8)
        self.client.logout()
        self.client.login(username="coord", password=PW)
        self.assertFalse(self.client.get(reverse("home")).context["user_prefs"]["saved"])

    def test_requires_login_post_and_csrf(self):
        r = self.client.post(self.url, "{}", content_type="application/json")
        self.assertEqual(r.status_code, 302)
        self.client.login(username="prof", password=PW)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.client.post(self.url, "não é json", content_type="application/json").status_code, 400)
        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        strict.login(username="prof", password=PW)
        self.assertEqual(strict.post(self.url, "{}", content_type="application/json").status_code, 403)
