"""O painel do EIA-Cognitio do professor não pode crescer em consultas a cada turma.

Na escala de uma escola real (um professor com 80 pares turma+disciplina) a página fazia ~460 consultas:
5 por par, mesmo nos pares sem prova ou atividade próxima, que não tinham o que analisar.
"""

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.academics.models import ClassGroup, TeacherAssignment

from apps.cognitio.evidence import rebuild_class

from .test_p17 import P17Base


class TeacherDashQueriesTests(P17Base):
    def _count(self):
        self.login(self.prof)
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(reverse("cognitio:dashboard")).status_code, 200)
        return len(ctx.captured_queries)

    def _more_classes(self, n, start):
        for i in range(n):
            cg = ClassGroup.objects.create(school=self.school, school_year=self.cg.school_year, name=f"Extra {start + i}")
            TeacherAssignment.objects.create(school=self.school, school_year=self.cg.school_year, teacher=self.prof,
                                             class_group=cg, subject=self.mat)

    def test_query_count_does_not_grow_with_idle_classes(self):
        self._more_classes(2, 0)
        few = self._count()
        self._more_classes(10, 2)
        self.assertLessEqual(self._count() - few, 2, "cada turma nova não pode custar consultas")


class OtherScreensQueriesTests(P17Base):
    """Grafo, observação e projeção: o custo não cresce com turmas, estudantes ou evidências."""

    def _queries(self, url):
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        return len(ctx.captured_queries), r

    def test_skill_graph_does_not_grow_with_teacher_classes(self):
        self.login(self.prof)
        url = reverse("cognitio:skill_graph", args=[self.h2.pk])
        few, _ = self._queries(url)
        TeacherDashQueriesTests._more_classes(self, 10, 0)
        more, r = self._queries(url)
        self.assertLessEqual(more - few, 2, "cada turma nova não pode custar consultas")
        self.assertContains(r, "Registrar observação · Extra 9")

    def test_observation_rows_apply_each_students_decision(self):
        from apps.cognitio.models import SkillJudgment

        SkillJudgment.objects.create(school=self.school, student=self.ana, item=self.h1, state="consolidada",
                                     rationale="Demonstrou com autonomia.", decided_by=self.prof, decided_on=self.today)
        self.login(self.prof)
        url = reverse("cognitio:observation_create", args=[self.cg.pk, self.mat.pk]) + f"?item={self.h1.pk}"
        _, r = self._queries(url)
        states = {row["s"]: row["state"][0] for row in r.context["rows"]}
        self.assertEqual((states[self.ana], states[self.bia]), ("consolidada", "nao_avaliado"))

    def test_evidence_links_one_query_per_source_type(self):
        from apps.cognitio.models import SkillEvidence
        from apps.cognitio.views_projection import evidence_url, evidence_urls
        from apps.pedagogy.models import Grade

        self.ev.curriculum.add(self.h1)
        self.ev.status = "publicada"  # só prova publicada vira evidência
        self.ev.save()
        for s in self.students:
            Grade.objects.create(school=self.school, evaluation=self.ev, student=s, value=7)
        self.obs(self.ana, self.h1, 2, 1)
        rebuild_class(self.cg)
        evs = list(SkillEvidence.objects.order_by("source_type", "pk"))
        self.assertEqual({e.source_type for e in evs}, {"avaliacao", "observacao"})
        with CaptureQueriesContext(connection) as ctx:
            urls = evidence_urls(evs)
        self.assertEqual(len(ctx.captured_queries), 1)  # notas numa consulta; observação não tem tela própria
        grade_url = reverse("pedagogy:evaluation_grade", args=[self.ev.pk])
        self.assertEqual(urls, [grade_url if e.source_type == "avaliacao" else None for e in evs])
        self.assertEqual(evidence_url(evs[0]), urls[0])
