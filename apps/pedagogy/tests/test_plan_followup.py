"""Plano de acompanhamento como objetivo acompanhável (Prompt 9 §5.7 e §12)
e escopo da coordenação restrita ao criar ou editar planos."""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.coordination.models import CoordinatorAssignment
from apps.core.models import AuditLog

from ..models import InterventionPlan, PlanNote
from .test_pedagogy import PedagogyBase


class PlanFollowUpTests(PedagogyBase):
    def make_plan(self, **extra):
        data = dict(school=self.school, student=self.ana, title="Leitura",
                    description="Ler 15 minutos por dia.", created_by=self.coord)
        data.update(extra)
        return InterventionPlan.objects.create(**data)

    def test_stale_and_overdue_signals(self):
        plan = self.make_plan(deadline=timezone.localdate() - timedelta(days=1))
        InterventionPlan.objects.filter(pk=plan.pk).update(
            created_at=timezone.now() - timedelta(days=45))
        plan.refresh_from_db()
        signals = plan.follow_up()
        self.assertTrue(signals["overdue"])
        self.assertEqual(signals["stale_days"], 45)
        # Um registro recente tira o "sem registro"; o prazo continua vencido.
        PlanNote.objects.create(plan=plan, note="Leu todos os dias.", created_by=self.coord)
        self.assertIsNone(plan.follow_up()["stale_days"])
        # Concluído não pede atenção.
        plan.status = InterventionPlan.Status.DONE
        self.assertEqual(plan.follow_up(), {"overdue": False, "stale_days": None})

    def test_list_and_detail_show_the_signals(self):
        self.make_plan(deadline=timezone.localdate() - timedelta(days=2),
                       success_criterion="Entregar tudo no prazo por um bimestre.")
        self.login("coord")
        lista = self.client.get(reverse("pedagogy:plan_list"))
        self.assertContains(lista, "prazo vencido")
        plan = InterventionPlan.objects.get()
        detalhe = self.client.get(reverse("pedagogy:plan_detail", args=[plan.pk]))
        self.assertContains(detalhe, "Prazo para reavaliar vencido")
        self.assertContains(detalhe, "Entregar tudo no prazo por um bimestre.")

    def test_coordination_edits_plan_but_not_the_student(self):
        plan = self.make_plan()
        self.login("coord")
        prazo = timezone.localdate() + timedelta(days=30)
        resp = self.client.post(reverse("pedagogy:plan_edit", args=[plan.pk]), {
            "student": self.bea.pk, "title": "Leitura diária", "description": plan.description,
            "success_criterion": "Ler um livro por mês.", "deadline": f"{prazo:%Y-%m-%d}",
            "status": "ativo",
        })
        self.assertEqual(resp.status_code, 302)
        plan.refresh_from_db()
        self.assertEqual(plan.student, self.ana)  # campo travado
        self.assertEqual(plan.deadline, prazo)
        self.assertEqual(plan.title, "Leitura diária")
        log = AuditLog.objects.filter(action="update", target_id=str(plan.pk)).latest("created_at")
        self.assertIn("prazo para reavaliar", log.detail)

    def test_only_coordination_edits(self):
        plan = self.make_plan()
        for user in ("prof", "dir", "resp"):
            self.login(user)
            self.assertEqual(self.client.get(reverse("pedagogy:plan_edit", args=[plan.pk])).status_code,
                             403, user)


class RestrictedCoordinationPlanTests(PedagogyBase):
    coordenacao_restrita = True

    def setUp(self):
        super().setUp()
        CoordinatorAssignment.objects.create(
            school=self.school, coordinator=self.coord, starts_on=timezone.localdate()
        ).class_groups.add(self.turma)  # só a turma da Ana

    def test_cannot_create_plan_outside_designation(self):
        self.login("coord")
        form = self.client.get(reverse("pedagogy:plan_create")).context["form"]
        self.assertEqual(list(form.fields["student"].queryset), [self.ana])
        resp = self.client.post(reverse("pedagogy:plan_create"), {
            "student": self.bea.pk, "title": "Fora", "description": "x", "status": "ativo"})
        self.assertNotEqual(resp.status_code, 302)
        self.assertFalse(InterventionPlan.objects.filter(student=self.bea).exists())

    def test_cannot_edit_plan_outside_designation(self):
        plan = InterventionPlan.objects.create(school=self.school, student=self.bea, title="B",
                                               description="x", created_by=self.direc)
        self.login("coord")
        self.assertEqual(self.client.get(reverse("pedagogy:plan_edit", args=[plan.pk])).status_code, 403)
