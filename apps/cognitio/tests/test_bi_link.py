"""Painel do estudante (BI) com as habilidades do EIA-Cognitio e períodos do calendário no seletor."""

from datetime import date

from django.urls import reverse

from apps.academics.models import SchoolYear
from apps.analytics import bi
from apps.cognitio.evidence import rebuild_class
from apps.cognitio.models import SkillObservation
from apps.cognitio.tests.test_evidence import Base
from apps.curriculum.models import CurriculumItem


class StudentPanelSkillsTests(Base):
    def setUp(self):
        super().setUp()
        geo_skill = CurriculumItem.objects.get(code="EF06GE01")
        for item, subject, teacher, lvl in ((self.h1, self.mat, self.prof, 5), (self.h2, self.mat, self.prof, 1),
                                            (geo_skill, self.geo, self.prof_geo, 3)):
            for _ in range(2):
                SkillObservation.objects.create(school=self.school, student=self.ana, item=item, class_group=self.cg,
                                                subject=subject, teacher=teacher, level=lvl, context="Sala")
        rebuild_class(self.cg)
        self.url = reverse("analytics:student_dashboard", args=[self.ana.pk])

    def test_team_sees_counts_by_component_within_their_subjects(self):
        self.login(self.prof)
        r = self.client.get(self.url)
        comps = {c["component"]: c for c in r.context["cognitio"]}
        self.assertEqual(set(comps), {"Matemática"})  # o professor de Matemática não vê Geografia
        self.assertEqual(comps["Matemática"]["total"], 2)
        self.assertContains(r, "Abrir o mapa do estudante")
        self.login(self.coord)
        self.assertEqual({c["component"] for c in self.client.get(self.url).context["cognitio"]},
                         {"Matemática", "Geografia"})

    def test_family_and_office_do_not_get_the_map(self):
        for user in (self.fam, self.sec):
            self.login(user)
            r = self.client.get(self.url)
            if r.status_code == 200:
                self.assertIsNone(r.context["cognitio"], user.username)
                self.assertNotContains(r, "Abrir o mapa do estudante")


class CalendarPeriodPresetTests(Base):
    def test_bimesters_in_selector_and_compared_with_previous_bimester(self):
        from apps.school_calendar.models import CalendarPeriod

        year = SchoolYear.objects.get(school=self.school)
        b1 = CalendarPeriod.objects.create(school=self.school, school_year=year, kind="bimestre", name="1º bimestre",
                                           start=date(2026, 2, 9), end=date(2026, 4, 24))
        b2 = CalendarPeriod.objects.create(school=self.school, school_year=year, kind="bimestre", name="2º bimestre",
                                           start=date(2026, 4, 27), end=date(2026, 7, 10))
        values = [v for v, _ in bi.presets_for(self.school)]
        self.assertEqual(values[-3:], [f"p{b1.pk}", f"p{b2.pk}", "personalizado"])
        p = bi.resolve_period({"periodo": f"p{b2.pk}"}, self.school)
        self.assertEqual((p.start, p.end, p.label), (b2.start, b2.end, "2º bimestre"))
        self.assertEqual((p.previous().start, p.previous().end), (b1.start, b1.end))
        self.assertEqual(bi.resolve_period({"periodo": "p999999"}, self.school).preset, "ano")
        self.login(self.coord)
        r = self.client.get(reverse("analytics:student_dashboard", args=[self.ana.pk]), {"periodo": f"p{b1.pk}"})
        self.assertContains(r, "1º bimestre (09/02 a 24/04)")
        q = bi.data_quality(self.school, p)
        self.assertNotIn("Bimestres", [name for name, _ in q["not_computable"]])
        self.assertNotIn("Habilidades por estudante", [name for name, _ in q["not_computable"]])
