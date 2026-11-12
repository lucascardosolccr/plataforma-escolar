"""Telas que não podem fazer uma consulta por turma, por ano do currículo ou por linha da auditoria.

Na base de escala (672 estudantes, professor com 88 pares turma+disciplina, 24 turmas) estas telas
faziam de 77 a 279 consultas: a escolha de turma lia o ano letivo de cada turma (o nome da turma o
mostra), o seletor de habilidades fazia duas consultas por componente × ano e o histórico da ficha lia
o autor de cada registro.
"""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.academics.models import ClassGroup, Subject, TeacherAssignment
from apps.communication.tests.test_communication import CommunicationBase
from apps.core.models import AuditLog, Role


class QueryBudgetTests(CommunicationBase):
    def _count(self, user, url):
        self.client.force_login(user)
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        return len(ctx.captured_queries)

    def test_class_choices_do_not_cost_a_query_per_class(self):
        url = reverse("communication:poll_create")
        few = self._count(self.direc, url)
        for i in range(10):
            ClassGroup.objects.create(school=self.school, school_year=self.year, name=f"Extra {i}")
        self.assertLessEqual(self._count(self.direc, url) - few, 1)

    def test_skill_picker_does_not_grow_with_years_and_components(self):
        url = reverse("pedagogy:activity_create")
        few = self._count(self.prof, url)
        port = Subject.objects.create(school=self.school, name="Língua Portuguesa")
        for n in range(2, 8):
            cg = ClassGroup.objects.create(school=self.school, school_year=self.year, name=f"{n}º Ano A")
            for subject in (self.mat, port):
                TeacherAssignment.objects.create(school=self.school, school_year=self.year, teacher=self.prof,
                                                 class_group=cg, subject=subject)
        # 12 grupos novos (2 componentes × 6 anos): no máximo uma consulta a mais por componente novo.
        self.assertLessEqual(self._count(self.prof, url) - few, 2)

    def test_notification_rules_does_not_query_per_event(self):
        # A tela lia o estado de cada evento com uma consulta por evento (~29: N+1).
        # Agora todas as regras da escola vêm numa consulta só.
        from apps.communication.family_events import EVENTS

        url = reverse("communication:notification_rules")
        self.assertLess(self._count(self.direc, url), len(EVENTS))

    def test_student_history_reads_authors_in_one_query(self):
        url = reverse("student_detail", args=[self.ana.pk])
        few = self._count(self.sec, url)
        for i in range(15):
            author = get_user_model().objects.create_user(f"autor{i}", password="senha-forte-1",
                                                          role=Role.SECRETARIA, school=self.school)
            AuditLog.objects.create(user=author, action="update", target_type="Student", target_id=str(self.ana.pk),
                                    detail=f"Alteração {i}", school=self.school)
        self.assertLessEqual(self._count(self.sec, url) - few, 1)
