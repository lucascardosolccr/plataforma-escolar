"""O painel da coordenação considera todas as turmas do alcance.

Antes, só as 15 primeiras em ordem alfabética entravam no cálculo: numa escola com mais turmas, os alertas
das demais nunca apareciam, e o indicador "Alertas" contava no máximo 3 por turma dessas 15.
"""

from unittest import mock

from django.urls import reverse

from apps.academics.models import ClassGroup

from .test_coordination import CoordBase


class PanelAllClassesTests(CoordBase):
    def test_alerts_come_from_every_class_and_the_most_reasons_first(self):
        year = self.a.school_year
        extra = [ClassGroup.objects.create(school=self.school, school_year=year, name=f"9º {i:02d}") for i in range(16)]
        last = extra[-1]  # "9º 15": a última em ordem alfabética, 18ª turma

        def fake_report(cg, period, **kw):
            follow = []
            if cg.pk == last.pk:
                follow = [{"student": self.bia, "reasons": ["frequência abaixo do limite", "2 disciplinas abaixo",
                                                            "entregas abaixo de 60%"]}]
            elif cg.pk == self.a.pk:
                follow = [{"student": self.ana, "reasons": ["1 disciplina abaixo"]}]
            return {"active": 1, "overall": {"mean": None}, "attendance": {"percent": None},
                    "delivery_rate": None, "follow_up": follow}

        self.login(self.dir)
        with mock.patch("apps.analytics.bi.class_report", side_effect=fake_report):
            resp = self.client.get(reverse("coordination:panel"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["class_rows"]), 18)
        self.assertEqual(resp.context["alerts_total"], 2)
        self.assertEqual([a["cg"].name for a in resp.context["alerts"]], ["9º 15", "7º A"])
        self.assertNotContains(resp, "Mostrando")
