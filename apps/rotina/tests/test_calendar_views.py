"""Visões mensal, semanal e agenda do calendário (Prompt 14 §4.4; Prompt 15 §6.1)."""

from django.urls import reverse

from apps.core.models import Role

from .test_rotina import Base


class CalendarViewsTests(Base):
    def test_month_week_and_agenda_views_show_the_same_event(self):
        self.login(Role.SECRETARIA)
        self.client.post(reverse("school_calendar:official"), {
            "form": "event", "e-kind": "feriado", "e-title": "Feriado municipal", "e-start": "2026-03-19",
            "e-audience": "todos"})
        self.login(Role.RESPONSAVEL)
        base = reverse("school_calendar:calendar_index")
        for query in ("?ver=mes&mes=2026-03", "?ver=semana&semana=2026-03-18",
                      "?ver=agenda&start=2026-03-01&end=2026-03-31"):
            with self.subTest(query=query):
                self.assertContains(self.client.get(base + query), "Feriado municipal")
        # Outra semana não traz o evento: a visão semanal recorta de fato o período.
        self.assertNotContains(self.client.get(base + "?ver=semana&semana=2026-03-04"), "Feriado municipal")
