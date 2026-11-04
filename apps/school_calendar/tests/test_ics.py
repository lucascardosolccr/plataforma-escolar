"""Agenda para o celular (.ics): os mesmos compromissos do calendário, sem registros sensíveis."""

from datetime import timedelta

from django.urls import reverse

from apps.core.models import AuditLog
from apps.pedagogy.models import Occurrence

from .test_calendar import CalendarBase


class CalendarIcsTests(CalendarBase):
    def _ics(self, user):
        self.login(user)
        resp = self.client.get(reverse("school_calendar:calendar_ics"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp["Content-Type"].startswith("text/calendar"))
        return resp.content.decode("utf-8")

    def test_family_gets_own_commitments_in_valid_format(self):
        self.make_activity(title="Atividade de frações, com vírgula; e ponto e vírgula")
        self.make_evaluation()
        self.make_activity(title="Atividade da outra turma", class_group=self.turma_b)
        Occurrence.objects.create(school=self.school, student=self.ana, description="Ocorrência da Ana", date=self.today)
        body = self._ics("resp")
        self.assertTrue(body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n"))
        self.assertIn(r"SUMMARY:Atividade de casa: Atividade de frações\, com vírgula\; e ponto e vírgula", body.replace("\r\n ", ""))
        self.assertIn("Avaliação: Prova de frações", body.replace("\r\n ", ""))
        self.assertIn(f"DTSTART;VALUE=DATE:{self.today + timedelta(days=2):%Y%m%d}", body)
        self.assertNotIn("outra turma", body)          # mesmo alcance do calendário
        self.assertNotIn("Ocorrência", body)            # registro sensível não vai para o arquivo
        for line in body.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75, line)
        self.assertTrue(AuditLog.objects.filter(action="export", detail__startswith="Baixou a agenda").exists())

    def test_line_breaks_inside_text_are_escaped(self):
        from apps.school_calendar.views import _ics_text

        self.assertEqual(_ics_text("linha 1\r\nlinha 2\nlinha 3"), r"linha 1\nlinha 2\nlinha 3")
        self.assertNotIn("\n", _ics_text("a\rb\nc"))  # quebra crua no valor partiria a propriedade do .ics

    def test_link_on_calendar_and_login_required(self):
        url = reverse("school_calendar:calendar_ics")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.login("resp")
        self.assertContains(self.calendar(), url)
