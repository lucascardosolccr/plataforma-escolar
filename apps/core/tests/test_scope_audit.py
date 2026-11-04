"""Auditoria de escopo: nenhuma rota de estudante ou turma abre para a coordenação restrita fora da designação.

Percorre TODAS as rotas cujo único parâmetro é ``student_id`` ou ``class_id``, inclusive as que forem criadas
depois, e abre cada uma com um estudante/turma fora da designação. Em 04/11/2026 a mesma auditoria, rodada à
mão, achou a edição de cadastro, a carteirinha, o histórico da portaria, mensagens, comunicados e a edição de
observações abertas fora da designação.
"""

from django.urls import NoReverseMatch, get_resolver, reverse
from django.utils import timezone

from apps.communication.tests.test_communication import CommunicationBase
from apps.coordination.models import CoordinatorAssignment

# Rotas que podem abrir fora da designação, com o motivo.
ALLOWED = {
    "rotina:schedule_class": "horário de aulas da turma: informação institucional, sem dado de estudante",
}
SKIP_PARTS = ("exportar", ".csv", ".xlsx", "baixar", "download", "foto", "anexo", "arquivo")


def _routes():
    def walk(patterns, ns=None):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                yield from walk(p.url_patterns, p.namespace or ns)
            elif p.name:
                yield (f"{ns}:{p.name}" if ns else p.name), set(getattr(p.pattern, "converters", {}))
    return list(walk(get_resolver().url_patterns))


class ScopeAuditTests(CommunicationBase):
    coordenacao_restrita = True

    def test_no_student_or_class_route_opens_outside_the_designation(self):
        CoordinatorAssignment.objects.create(school=self.school, coordinator=self.coord,
                                             starts_on=timezone.localdate()).class_groups.add(self.turma)
        self.client.force_login(self.coord)
        checked, leaks = 0, []
        for name, params in _routes():
            for key, outside in (("student_id", self.bea.pk), ("class_id", self.turma_b.pk)):
                if params != {key} or name in ALLOWED:
                    continue
                try:
                    url = reverse(name, kwargs={key: outside})
                except NoReverseMatch:
                    continue
                if any(part in url for part in SKIP_PARTS):
                    continue
                checked += 1
                if self.client.get(url).status_code == 200:
                    leaks.append(f"{name} {url}")
        self.assertGreater(checked, 15)  # a auditoria de fato percorreu as rotas
        self.assertEqual(leaks, [], "rotas que abrem fora da designação da coordenação")


class TeacherAndFamilyScopeAuditTests(CommunicationBase):
    """Professor só nas turmas em que leciona; família só nos filhos com vínculo aprovado."""

    def _leaks(self, user, student, class_group):
        self.client.force_login(user)
        leaks = []
        for name, params in _routes():
            for key, outside in (("student_id", student.pk), ("class_id", class_group.pk)):
                if params != {key} or name in ALLOWED:
                    continue
                try:
                    url = reverse(name, kwargs={key: outside})
                except NoReverseMatch:
                    continue
                if not any(part in url for part in SKIP_PARTS) and self.client.get(url).status_code == 200:
                    leaks.append(f"{name} {url}")
        return leaks

    def test_teacher_routes_stay_in_own_classes(self):
        self.assertEqual(self._leaks(self.prof, self.bea, self.turma_b), [])

    def test_family_routes_stay_with_own_children(self):
        self.assertEqual(self._leaks(self.resp, self.bea, self.turma_b), [])
