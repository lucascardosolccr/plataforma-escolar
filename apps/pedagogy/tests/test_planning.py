"""Planejamento docente, realização da atividade e vigência da disciplina."""

from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.communication.models import Notification
from apps.coordination.models import CoordinatorAssignment
from apps.core.models import AuditLog, Role, School, User
from apps.pedagogy.models import Activity, LessonPlan, LessonPlanReview

PW = "Senha-forte-123"


class PlanBase(TestCase):
    coordenacao_restrita = True

    def setUp(self):
        self.school = School.objects.create(name="Escola", code="e")
        self.year = SchoolYear.objects.create(school=self.school, name="2026", is_current=True)
        self.a = ClassGroup.objects.create(school=self.school, school_year=self.year, name="7º A")
        self.b = ClassGroup.objects.create(school=self.school, school_year=self.year, name="7º B")
        self.mat = Subject.objects.create(school=self.school, name="Matemática")
        self.port = Subject.objects.create(school=self.school, name="Português")
        mk = lambda u, r: User.objects.create_user(u, password=PW, role=r, school=self.school, first_name=u.title())
        self.prof = mk("prof", Role.PROFESSOR)
        self.prof2 = mk("prof2", Role.PROFESSOR)
        self.coord_a = mk("coorda", Role.COORDENACAO)
        self.coord_b = mk("coordb", Role.COORDENACAO)
        self.dir = mk("dir", Role.DIRECAO)
        for t, cg, s in ((self.prof, self.a, self.mat), (self.prof2, self.b, self.port)):
            TeacherAssignment.objects.create(school=self.school, school_year=self.year, teacher=t,
                                             class_group=cg, subject=s)
        for coord, cg in ((self.coord_a, self.a), (self.coord_b, self.b)):
            d = CoordinatorAssignment.objects.create(school=self.school, coordinator=coord,
                                                     starts_on=timezone.localdate())
            d.class_groups.add(cg)
        self.monday = date(2026, 11, 2)

    def login(self, user):
        self.client.logout()
        self.client.login(username=user.username, password=PW)

    def data(self, **kw):
        d = {"class_group": self.a.pk, "subject": self.mat.pk, "starts_on": "2026-11-02",
             "ends_on": "2026-11-06", "title": "Frações", "content": "Frações equivalentes",
             "objectives": "Comparar frações", "methodology": "", "resources": "", "assessment": ""}
        d.update(kw)
        return d

    def make(self, status="rascunho", **kw):
        return LessonPlan.objects.create(
            school=self.school, teacher=kw.pop("teacher", self.prof), class_group=kw.pop("cg", self.a),
            subject=kw.pop("subject", self.mat), starts_on=kw.pop("starts_on", self.monday),
            ends_on=kw.pop("ends_on", self.monday + timedelta(days=4)), title="Frações", content="c",
            objectives="o", status=status, **kw)


class TeacherFlowTests(PlanBase):
    def test_create_only_for_own_pair(self):
        self.login(self.prof)
        r = self.client.post(reverse("pedagogy:lessonplan_create"), self.data())
        plan = LessonPlan.objects.get()
        self.assertRedirects(r, reverse("pedagogy:lessonplan_detail", args=[plan.pk]))
        self.assertEqual((plan.teacher, plan.status), (self.prof, "rascunho"))
        # URL forjada: turma ou disciplina de outro professor.
        for forged in (self.data(subject=self.port.pk), self.data(class_group=self.b.pk)):
            r = self.client.post(reverse("pedagogy:lessonplan_create"), forged)
            self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse("pedagogy:lessonplan_create"), self.data(ends_on="2026-10-30"))
        self.assertContains(r, "O fim não pode ser antes do início")
        self.assertEqual(LessonPlan.objects.count(), 1)

    def test_draft_is_private_and_submit_notifies_only_the_coordinator_in_scope(self):
        plan = self.make()
        self.login(self.coord_a)
        self.assertEqual(self.client.get(reverse("pedagogy:lessonplan_detail", args=[plan.pk])).status_code, 403)
        self.login(self.prof)
        url = reverse("pedagogy:lessonplan_submit", args=[plan.pk])
        self.client.post(url)
        self.client.post(url)  # segundo clique não envia de novo
        plan.refresh_from_db()
        self.assertEqual(plan.status, "enviado")
        self.assertEqual(Notification.objects.filter(user=self.coord_a, kind="planejamento").count(), 1)
        self.assertFalse(Notification.objects.filter(user=self.coord_b).exists())
        self.assertFalse(Notification.objects.filter(user=self.dir).exists())  # há coordenação na turma
        # Enviado não se edita.
        r = self.client.get(reverse("pedagogy:lessonplan_edit", args=[plan.pk]))
        self.assertRedirects(r, reverse("pedagogy:lessonplan_detail", args=[plan.pk]))

    def test_adjust_cycle_and_validation(self):
        plan = self.make(status="enviado")
        review = reverse("pedagogy:lessonplan_review", args=[plan.pk])
        self.login(self.coord_a)
        r = self.client.post(review, {"decision": "ajustes", "comment": ""})
        self.assertContains(r, "Explique o que ajustar")
        self.client.post(review, {"decision": "ajustes", "comment": "Inclua uma atividade prática."})
        plan.refresh_from_db()
        self.assertEqual(plan.status, "ajustes")
        n = Notification.objects.get(user=self.prof)
        self.assertEqual(n.title, "Planejamento devolvido para ajustes: Frações")
        # O professor vê a orientação ao editar, corrige e reenvia.
        self.login(self.prof)
        self.assertContains(self.client.get(reverse("pedagogy:lessonplan_edit", args=[plan.pk])),
                            "Inclua uma atividade prática.")
        self.client.post(reverse("pedagogy:lessonplan_edit", args=[plan.pk]),
                         self.data(methodology="Material concreto"))
        self.client.post(reverse("pedagogy:lessonplan_submit", args=[plan.pk]))
        self.login(self.coord_a)
        self.client.post(review, {"decision": "validado", "comment": ""})
        plan.refresh_from_db()
        self.assertEqual((plan.status, plan.methodology), ("validado", "Material concreto"))
        self.assertEqual(list(LessonPlanReview.objects.values_list("decision", flat=True)), ["ajustes", "validado"])
        self.assertTrue(AuditLog.objects.filter(action="approve", detail__startswith="Validou").exists())
        # Analisado não se analisa de novo.
        self.client.post(review, {"decision": "ajustes", "comment": "x"})
        self.assertEqual(LessonPlanReview.objects.count(), 2)

    def test_duplicate_and_delete(self):
        plan = self.make(status="validado")
        self.login(self.prof)
        self.client.post(reverse("pedagogy:lessonplan_duplicate", args=[plan.pk]))
        copy = LessonPlan.objects.exclude(pk=plan.pk).get()
        self.assertEqual((copy.status, copy.starts_on, copy.ends_on),
                         ("rascunho", self.monday + timedelta(days=7), self.monday + timedelta(days=11)))
        self.client.post(reverse("pedagogy:lessonplan_delete", args=[plan.pk]))  # validado não se exclui
        self.client.post(reverse("pedagogy:lessonplan_delete", args=[copy.pk]))
        self.assertEqual(list(LessonPlan.objects.values_list("pk", flat=True)), [plan.pk])


class AccessTests(PlanBase):
    def test_who_sees_what(self):
        sent_a = self.make(status="enviado")
        sent_b = self.make(status="enviado", teacher=self.prof2, cg=self.b, subject=self.port)
        draft_b = self.make(teacher=self.prof2, cg=self.b, subject=self.port)
        detail = lambda p: reverse("pedagogy:lessonplan_detail", args=[p.pk])
        lst = reverse("pedagogy:lessonplan_list") + "?situacao="
        self.login(self.coord_a)
        r = self.client.get(lst)
        self.assertEqual([p.pk for p in r.context["plans"]], [sent_a.pk])
        self.assertEqual(self.client.get(detail(sent_b)).status_code, 403)
        self.assertEqual(self.client.post(reverse("pedagogy:lessonplan_review", args=[sent_b.pk]),
                                          {"decision": "validado"}).status_code, 403)
        self.login(self.dir)
        self.assertEqual({p.pk for p in self.client.get(lst).context["plans"]}, {sent_a.pk, sent_b.pk})
        self.assertEqual(self.client.get(detail(draft_b)).status_code, 403)
        self.login(self.prof)  # outro professor
        self.assertEqual(self.client.get(detail(sent_b)).status_code, 403)
        self.assertEqual(self.client.post(reverse("pedagogy:lessonplan_submit", args=[draft_b.pk])).status_code, 403)
        for role in (Role.SECRETARIA, Role.ADMIN, Role.RESPONSAVEL, Role.ESTUDANTE):
            u = User.objects.create_user(f"x{role}", password=PW, role=role, school=self.school)
            self.login(u)
            self.assertEqual(self.client.get(lst).status_code, 403, role)
            self.assertEqual(self.client.get(detail(sent_a)).status_code, 403, role)

    def test_other_school_is_404(self):
        other = School.objects.create(name="Outra", code="o")
        u = User.objects.create_user("dir2", password=PW, role=Role.DIRECAO, school=other)
        plan = self.make(status="enviado")
        self.login(u)
        self.assertEqual(self.client.get(reverse("pedagogy:lessonplan_detail", args=[plan.pk])).status_code, 404)

    def test_pending_and_panel_coverage(self):
        from apps.pedagogy.views_planning import week_coverage

        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        self.make(status="enviado", starts_on=monday, ends_on=monday + timedelta(days=4))
        cov = week_coverage(self.dir, today)
        self.assertEqual((cov["total"], cov["covered"]), (2, 1))
        self.assertEqual([(c, s) for c, s, _ in cov["missing"]], [(self.b, self.port)])
        self.assertEqual(week_coverage(self.coord_a, today)["total"], 1)  # só a turma A
        self.login(self.coord_a)
        self.assertContains(self.client.get(reverse("pending_center")), "Planejamentos aguardando devolutiva")
        r = self.client.get(reverse("coordination:panel"))
        self.assertEqual(r.context["plans_waiting"], 1)
        self.assertContains(r, "Planejamento desta semana")


class ActivityFieldsTests(PlanBase):
    def test_form_shows_and_keeps_content_objective_notes_and_mode(self):
        self.login(self.prof)
        page = self.client.get(reverse("pedagogy:activity_create"))
        for name in ("content", "objective", "internal_notes", "work_mode"):
            self.assertContains(page, f'name="{name}"')
        self.assertContains(page, "Data de aplicação")
        data = {"class_group": self.a.pk, "subject": self.mat.pk, "title": "Mapa", "description": "Faça",
                "class_date": "2026-11-03", "work_mode": "grupo", "content": "Relevo", "objective": "Ler mapas",
                "internal_notes": "Levar atlas"}
        self.client.post(reverse("pedagogy:activity_create"), data)
        act = Activity.objects.get()
        self.assertEqual((act.work_mode, act.content, act.objective, act.internal_notes),
                         ("grupo", "Relevo", "Ler mapas", "Levar atlas"))
        page = self.client.get(reverse("pedagogy:activity_edit", args=[act.pk]))
        self.assertContains(page, "Levar atlas")
        data["title"] = "Mapa 2"
        self.client.post(reverse("pedagogy:activity_edit", args=[act.pk]), data)
        act.refresh_from_db()
        self.assertEqual((act.title, act.content, act.internal_notes), ("Mapa 2", "Relevo", "Levar atlas"))
        self.assertContains(self.client.get(reverse("pedagogy:activity_detail", args=[act.pk])), "Em grupo")


class SubjectValidityTests(PlanBase):
    def test_out_of_validity_leaves_choices_but_keeps_history(self):
        today = timezone.localdate()
        self.port.valid_until = today - timedelta(days=1)
        self.port.save()
        art = Subject.objects.create(school=self.school, name="Artes", valid_from=today + timedelta(days=10))
        self.assertEqual(set(Subject.choices_for(self.school)), {self.mat})
        self.assertEqual(self.port.availability(today), f"Vigência encerrada em {self.port.valid_until:%d/%m/%Y}")
        self.assertTrue(art.availability(today).startswith("A partir de"))
        # Registro antigo com a disciplina encerrada continua editável.
        self.assertIn(self.port, Subject.choices_for(self.school, keep=self.port.pk))
        sec = User.objects.create_user("sec", password=PW, role=Role.SECRETARIA, school=self.school)
        self.login(sec)
        r = self.client.get(reverse("assignment_create"))
        names = [s.name for s in r.context["form"].fields["subject"].queryset]
        self.assertEqual(names, ["Matemática"])
        self.assertContains(self.client.get(reverse("subject_list")), "Vigência encerrada")

    def test_subject_form_rejects_inverted_validity(self):
        sec = User.objects.create_user("sec", password=PW, role=Role.SECRETARIA, school=self.school)
        self.login(sec)
        r = self.client.post(reverse("subject_create"), {"name": "Música", "is_active": "on",
                                                         "valid_from": "2026-12-01", "valid_until": "2026-11-01"})
        self.assertContains(r, "O fim da vigência não pode ser antes do início")
        self.assertFalse(Subject.objects.filter(name="Música").exists())

    def test_mode_defaults_to_individual_when_not_sent(self):
        self.login(self.prof)
        self.client.post(reverse("pedagogy:activity_create"), {
            "class_group": self.a.pk, "subject": self.mat.pk, "title": "Leitura", "description": "Leia",
            "class_date": "2026-11-03"})
        self.assertEqual(Activity.objects.get().work_mode, "individual")
