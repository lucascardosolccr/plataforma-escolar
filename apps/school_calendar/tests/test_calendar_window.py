"""Período padrão e filtragem no banco do calendário.

Sem período escolhido, o calendário carregava todo o histórico da escola —
atividades, avaliações, ocorrências e justificativas — e filtrava em Python
a cada acesso. Para a família, trazia as atividades de todas as turmas para
descartar quase todas.
"""

from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.pedagogy.models import Activity

from .test_calendar import CalendarBase


class CalendarWindowTests(CalendarBase):
    def calendar(self, **params):
        return self.client.get(reverse("school_calendar:calendar_index"), params)

    def test_default_window_hides_old_history(self):
        self.make_activity(
            title="Tarefa antiga",
            published_date=self.today - timedelta(days=90),
            deadline=self.today - timedelta(days=80),
        )
        self.make_activity(title="Tarefa da semana")
        self.login("resp")
        resp = self.calendar()
        self.assertTrue(resp.context["default_window"])
        self.assertContains(resp, "Tarefa da semana")
        self.assertNotContains(resp, "Tarefa antiga")

    def test_explicit_period_reaches_old_history(self):
        self.make_activity(
            title="Tarefa antiga",
            published_date=self.today - timedelta(days=90),
            deadline=self.today - timedelta(days=80),
        )
        self.login("resp")
        resp = self.calendar(
            start=(self.today - timedelta(days=100)).isoformat(),
            end=self.today.isoformat(),
        )
        self.assertFalse(resp.context["default_window"])
        self.assertContains(resp, "Tarefa antiga")

    def test_activity_without_deadline_uses_publication_date(self):
        self.make_activity(title="Leitura livre", deadline=None)
        self.login("resp")
        self.assertContains(self.calendar(), "Leitura livre")

    def test_family_query_does_not_load_other_classes(self):
        """A família não puxa do banco as atividades de turmas alheias."""
        for i in range(15):
            self.make_activity(
                title=f"Outra turma {i}", class_group=self.turma_b,
                subject=self.port, created_by=self.prof2,
            )
        self.make_activity(title="Da turma da Ana")
        self.login("resp")
        with CaptureQueriesContext(connection) as ctx:
            resp = self.calendar(type="activity")
        self.assertContains(resp, "Da turma da Ana")
        self.assertNotContains(resp, "Outra turma")
        sql = " ".join(q["sql"] for q in ctx.captured_queries if "pedagogy_activity" in q["sql"])
        self.assertIn("class_group_id", sql)

    def test_scope_still_enforced_with_period(self):
        self.make_activity(
            title="Atividade de outra turma", class_group=self.turma_b,
            subject=self.port, created_by=self.prof2,
        )
        self.login("resp")
        resp = self.calendar(
            start=(self.today - timedelta(days=5)).isoformat(),
            end=(self.today + timedelta(days=5)).isoformat(),
        )
        self.assertNotContains(resp, "Atividade de outra turma")

    def test_canceled_draft_absent_even_for_explicit_period(self):
        self.make_activity(
            title="Rascunho cancelado", status=Activity.Status.CANCELED,
            visible_before_cancel=False,
        )
        self.login("resp")
        resp = self.calendar(
            start=(self.today - timedelta(days=5)).isoformat(),
            end=(self.today + timedelta(days=5)).isoformat(),
        )
        self.assertNotContains(resp, "Rascunho cancelado")
