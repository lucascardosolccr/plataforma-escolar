"""Todo link que a plataforma mostra abre para quem o vê.

Com a escola de demonstração, cada perfil navega pelos links internos (GET, até 3 níveis, no máximo duas
páginas por padrão de URL) e nenhum pode dar 403 ou 500, nem redirecionar com mensagem de erro ou de
aviso (o "Editar" de uma avaliação já publicada só devolvia "apenas rascunhos podem ser alterados"). Uma varredura assim achou 12 links que levavam a
"acesso negado" (por exemplo, a coordenação via "Analisar pré-cadastros", que é da secretaria).
"""

import re
from collections import Counter

from django.contrib.messages import WARNING, get_messages
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.core.models import User

SKIP = re.compile(r"/(sair|logout|admin)/|/download|\.(pdf|csv|xlsx|zip|png|jpg|ics)$|/exportar|/backup|/imprimir"
                  r"|/media/|/foto/?$|/static/")
LINK = re.compile(r'href="(/[^"#]*)"')


def _pattern(path):
    return re.sub(r"/\d+", "/<id>", path.split("?")[0])


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
class LinkIntegrityTests(TestCase):
    coordenacao_restrita = True  # conftest: a coordenadora restrita fica mesmo restrita

    @classmethod
    def setUpTestData(cls):
        from apps.academics.models import ClassGroup
        from apps.coordination.models import CoordinatorAssignment
        from apps.core.models import Role

        call_command("seeddemo", verbosity=0)
        demo = User.objects.get(username="demo.coordenacao")
        # coordenador que acompanha uma turma só: as telas não podem oferecer o resto da escola
        cls.restricted = User.objects.create_user("coord.restrita", password="Senha-forte-123",
                                                  role=Role.COORDENACAO, school=demo.school)
        cls.one_class = ClassGroup.objects.filter(school=demo.school).order_by("name").first()
        d = CoordinatorAssignment.objects.create(school=demo.school, coordinator=cls.restricted,
                                                 starts_on=demo.coordination_assignments.first().starts_on)
        d.class_groups.set([cls.one_class])

    def test_restricted_coordinator_calendar_stays_in_scope(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.pedagogy.models import Activity, Occurrence

        self.client.force_login(self.restricted)
        today = timezone.localdate()
        r = self.client.get("/calendario/", {"start": (today - timedelta(days=60)).isoformat(),
                                             "end": (today + timedelta(days=60)).isoformat()})
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        outside = Activity.objects.filter(school=self.restricted.school).exclude(class_group=self.one_class)
        self.assertTrue(outside.exists())
        for act in outside:
            self.assertNotIn(f"/atividades/{act.pk}/\"", html)
        for oc in Occurrence.objects.filter(school=self.restricted.school).select_related("student"):
            if not oc.student.enrollments.filter(class_group=self.one_class, status="ativo").exists():
                self.assertNotIn(f"/ocorrencias/{oc.pk}/\"", html)

    def test_no_shown_link_leads_to_forbidden_or_error(self):
        users = {}
        for u in User.objects.filter(is_active=True, school__code="demo").order_by("pk"):
            users.setdefault(u.role, u)
        users["coordenacao restrita"] = self.restricted
        self.assertGreaterEqual(len(users), 6)
        broken = []
        for role, user in users.items():
            self.client.force_login(user)
            seen, per_pattern, frontier = set(), Counter(), [("/", None)]
            for _ in range(3):
                nxt = []
                for path, origin in frontier:
                    path = path.replace("&amp;", "&")
                    pat = _pattern(path)
                    if path in seen or SKIP.search(path) or per_pattern[pat] >= 2 or len(seen) >= 150:
                        continue
                    seen.add(path)
                    per_pattern[pat] += 1
                    r = self.client.get(path)
                    if r.status_code in (403, 500):
                        broken.append(f"{role}: {path} ({r.status_code}) — link em {origin}")
                    elif r.status_code == 302:
                        refused = [str(m) for m in get_messages(r.wsgi_request) if m.level >= WARNING]
                        if refused:
                            broken.append(f"{role}: {path} (302: {refused[0]}) — link em {origin}")
                    elif r.status_code == 200 and "text/html" in r.get("Content-Type", ""):
                        nxt += [(link, path) for link in LINK.findall(r.content.decode("utf-8", "ignore"))]
                frontier = nxt
        self.assertEqual(broken, [])
