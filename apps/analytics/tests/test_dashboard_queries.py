"""Os painéis não fazem consultas por estudante nem por turma.

O painel da turma fazia ~8 consultas por estudante (175 numa turma de 18 da
demonstração) e o institucional, três por turma. Os testes medem com dois
tamanhos e falham se o número de consultas crescer com o volume.
"""

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.academics.models import ClassGroup, TeacherAssignment
from apps.pedagogy.models import Occurrence
from apps.registry.models import Enrollment, Student

from .. import services
from .test_analytics import AnalyticsBase


class DashboardQueryTests(AnalyticsBase):
    def add_students(self, n, class_group):
        for i in range(n):
            st = Student.objects.create(school=self.school, first_name=f"Aluno{i}")
            Enrollment.objects.create(
                school=self.school, student=st, class_group=class_group,
                school_year=self.year,
            )
            self.make_evaluation(st, 4 if i % 2 else 8)
            self.make_attendance(st, present=3, absent=2 if i % 3 else 0,
                                 class_group=class_group)
            if i % 4 == 0:
                Occurrence.objects.create(
                    school=self.school, student=st, description="x",
                    recorded_by=self.prof,
                )

    def count(self, url):
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return len(ctx)

    def test_class_dashboard_does_not_grow_with_students(self):
        self.login("coord")
        url = reverse("analytics:class_dashboard", args=[self.turma.pk])
        self.add_students(2, self.turma)
        small = self.count(url)
        self.add_students(15, self.turma)
        large = self.count(url)
        self.assertEqual(small, large, f"consultas subiram de {small} para {large}")

    def test_institutional_dashboard_does_not_grow_with_classes(self):
        self.login("coord")
        url = reverse("analytics:institutional_dashboard")
        small = self.count(url)
        for i in range(6):
            cg = ClassGroup.objects.create(
                school=self.school, school_year=self.year, name=f"Turma {i}"
            )
            self.add_students(2, cg)
        large = self.count(url)
        self.assertEqual(small, large, f"consultas subiram de {small} para {large}")

    def test_subject_dashboard_does_not_grow_with_classes(self):
        """Painel por disciplina: antes, 6 consultas por turma (140 numa escola de 24 turmas)."""
        self.login("coord")
        url = reverse("analytics:subject_dashboard", args=[self.mat.pk])
        self.add_students(2, self.turma)
        small = self.count(url)
        for i in range(5):
            cg = ClassGroup.objects.create(school=self.school, school_year=self.year, name=f"Turma D{i}")
            # o painel só considera turmas com a disciplina atribuída
            TeacherAssignment.objects.create(school=self.school, school_year=self.year, teacher=self.prof,
                                             class_group=cg, subject=self.mat)
            self.add_students(2, cg)
        large = self.count(url)
        self.assertEqual(small, large, f"consultas subiram de {small} para {large}")

    def test_attention_list_matches_individual_rules(self):
        """O cálculo em lote dá o mesmo resultado do cálculo por estudante."""
        self.add_students(9, self.turma)
        esperado = []
        for st in services.class_students(self.turma):
            motivos = []
            baixas = [
                a for a in services.subject_averages(st)
                if a["average"] is not None and a["average"] < a["passing"]
            ]
            if baixas:
                motivos.append(f"{len(baixas)} disciplina(s) abaixo da média")
            att = services.attendance_stats(st)
            if att["near_limit"]:
                motivos.append(
                    f"faltas em {att['absence_percent']}% (limite {att['limit']}%)"
                )
            if st.occurrences.filter(
                status__in=[Occurrence.Status.OPEN, Occurrence.Status.FOLLOW_UP]
            ).exists():
                motivos.append("ocorrência em aberto")
            if motivos:
                esperado.append((st.pk, motivos))
        obtido = [
            (f["student"].pk, f["reasons"])
            for f in services.students_needing_attention(self.turma)
        ]
        self.assertTrue(esperado)
        self.assertEqual(obtido, esperado)
