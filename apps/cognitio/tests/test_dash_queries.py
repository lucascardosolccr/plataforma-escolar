"""O painel do EIA-Cognitio do professor não pode crescer em consultas a cada turma.

Na escala de uma escola real (um professor com 80 pares turma+disciplina) a página fazia ~460 consultas:
5 por par, mesmo nos pares sem prova ou atividade próxima, que não tinham o que analisar.
"""

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.academics.models import ClassGroup, TeacherAssignment

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
