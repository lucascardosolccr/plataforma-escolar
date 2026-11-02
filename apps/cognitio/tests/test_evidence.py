"""Modelo de evidências e motor de domínio (Prompt 16, etapas 3 e 4)."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.cognitio.evidence import rebuild_class
from apps.cognitio.mastery import assess
from apps.cognitio.models import MasteryScale, Question, QuestionResponse, SkillEvidence, SkillObservation
from apps.coordination.models import CoordinatorAssignment
from apps.core.models import AuditLog, Role, School, User
from apps.curriculum.models import CurriculumItem
from apps.pedagogy.models import Activity, Evaluation, Grade, Submission
from apps.registry.models import Enrollment, GuardianLink, Student

PW = "Senha-forte-123"


def ev(day, ratio, weight=1.0, source="questao"):
    return SimpleNamespace(observed_on=day, ratio=ratio, weight=weight, pk=None, source_type=source,
                           get_source_type_display=lambda: source)


class MasteryRulesTests(TestCase):
    def setUp(self):
        self.scale = MasteryScale(school=School(name="x"))
        self.today = date(2026, 10, 31)

    def test_states_follow_explicit_criteria(self):
        d = self.today
        self.assertEqual(assess([], self.scale, d).state, "nao_avaliado")
        self.assertEqual(assess([ev(d, 0.1)], self.scale, d).state, "insuficiente")  # uma só
        blanks = [ev(d, None, 0.0), ev(d, None, 0.0), ev(d, None, 0.0)]
        a = assess(blanks, self.scale, d)
        self.assertEqual((a.state, a.n_without), ("insuficiente", 3))  # ausência não é dificuldade
        self.assertEqual(assess([ev(d, 0.2), ev(d, 0.3)], self.scale, d).state, "dificuldade")
        self.assertEqual(assess([ev(d, 0.5), ev(d, 0.55)], self.scale, d).state, "desenvolvimento")
        self.assertEqual(assess([ev(d, 0.7), ev(d, 0.75)], self.scale, d).state, "consolidacao")
        self.assertEqual(assess([ev(d, 0.9), ev(d, 1.0)], self.scale, d).state, "consolidada")
        self.assertEqual(assess([ev(d, 0.0), ev(d, 1.0)], self.scale, d).state, "contraditoria")

    def test_recency_trend_and_configurable_cuts(self):
        d = self.today
        old_bad = [ev(d - timedelta(days=400), 0.1), ev(d - timedelta(days=380), 0.1)]
        recent_good = [ev(d - timedelta(days=5), 0.75), ev(d - timedelta(days=2), 0.8)]
        a = assess(old_bad + recent_good, self.scale, d)
        self.assertGreater(a.mean, 0.6)  # o recente pesa mais
        self.assertEqual(a.trend, "evolucao")
        dip = [ev(d - timedelta(days=30), 0.8), ev(d - timedelta(days=20), 0.8), ev(d - timedelta(days=10), 0.4),
               ev(d - timedelta(days=5), 0.85)]
        self.assertNotEqual(assess(dip, self.scale, d).trend, "queda")  # queda pontual não é regressão
        down = [ev(d - timedelta(days=40), 0.9), ev(d - timedelta(days=30), 0.9), ev(d - timedelta(days=10), 0.3),
                ev(d - timedelta(days=5), 0.3)]
        self.assertEqual(assess(down, self.scale, d).trend, "queda")
        self.scale.t3 = 0.95
        self.assertEqual(assess([ev(d, 0.9), ev(d, 0.9)], self.scale, d).state, "consolidacao")
        self.scale.min_evidence = 3
        self.assertEqual(assess([ev(d, 0.9), ev(d, 0.9)], self.scale, d).state, "insuficiente")


class Base(TestCase):
    coordenacao_restrita = True

    def setUp(self):
        self.today = timezone.localdate()
        self.school = School.objects.create(name="Escola", code="e")
        year = SchoolYear.objects.create(school=self.school, name="2026", is_current=True)
        self.cg = ClassGroup.objects.create(school=self.school, school_year=year, name="6º Ano A")
        self.cg_b = ClassGroup.objects.create(school=self.school, school_year=year, name="6º Ano B")
        self.mat = Subject.objects.create(school=self.school, name="Matemática")
        self.geo = Subject.objects.create(school=self.school, name="Geografia")
        mk = lambda u, r: User.objects.create_user(u, password=PW, role=r, school=self.school, first_name=u.title())
        self.prof, self.prof_geo, self.prof_b = mk("prof", Role.PROFESSOR), mk("profgeo", Role.PROFESSOR), mk("profb", Role.PROFESSOR)
        self.coord, self.coord_b = mk("coord", Role.COORDENACAO), mk("coordb", Role.COORDENACAO)
        self.dir, self.sec, self.fam = mk("dir", Role.DIRECAO), mk("sec", Role.SECRETARIA), mk("fam", Role.RESPONSAVEL)
        for t, cg, s in ((self.prof, self.cg, self.mat), (self.prof_geo, self.cg, self.geo), (self.prof_b, self.cg_b, self.mat)):
            TeacherAssignment.objects.create(school=self.school, school_year=year, teacher=t, class_group=cg, subject=s)
        for c, cg in ((self.coord, self.cg), (self.coord_b, self.cg_b)):
            CoordinatorAssignment.objects.create(school=self.school, coordinator=c, starts_on=self.today).class_groups.add(cg)
        self.students = []
        for name in ("Ana", "Bia", "Caio"):
            s = Student.objects.create(school=self.school, first_name=name)
            Enrollment.objects.create(school=self.school, student=s, class_group=self.cg, school_year=year)
            self.students.append(s)
        self.ana, self.bia, self.caio = self.students
        GuardianLink.objects.create(school=self.school, guardian=self.fam, student=self.ana, status="aprovado")
        self.h1 = CurriculumItem.objects.get(code="EF06MA01")
        self.h2 = CurriculumItem.objects.get(code="EF06MA03")
        self.ev = Evaluation.objects.create(school=self.school, class_group=self.cg, subject=self.mat, title="Prova 1",
                                            date=self.today, created_by=self.prof)

    def login(self, user):
        self.client.logout()
        self.client.login(username=user.username, password=PW)


class QuestionFlowTests(Base):
    def test_questions_responses_evidence_and_grades(self):
        self.login(self.prof)
        url = reverse("cognitio:questions", args=[self.ev.pk])
        for n, main in ((1, self.h1), (2, self.h2)):
            r = self.client.post(url, {"number": n, "label": f"Questão {n}", "main_skill": main.pk,
                                       "secondary_codes": "EF06MA02" if n == 1 else "", "max_points": "2",
                                       "complexity": 2, "evidence_type": "procedimento"})
            self.assertEqual(r.status_code, 302)
        q1, q2 = Question.objects.order_by("number")
        self.assertEqual(sorted(q1.questionskill_set.values_list("role", flat=True)), ["principal", "secundaria"])
        self.assertIn(self.h1, self.ev.curriculum.all())
        data = {f"p_{q1.pk}_{self.ana.pk}": "2", f"s_{q1.pk}_{self.ana.pk}": "respondida",
                f"p_{q2.pk}_{self.ana.pk}": "0,5", f"s_{q2.pk}_{self.ana.pk}": "respondida",
                f"e_{q2.pk}_{self.ana.pk}": "conceitual",
                f"s_{q1.pk}_{self.bia.pk}": "ausente", f"s_{q2.pk}_{self.bia.pk}": "ausente",
                f"p_{q1.pk}_{self.caio.pk}": "9", f"s_{q1.pk}_{self.caio.pk}": "respondida",
                "atualizar_notas": "1"}
        r = self.client.post(reverse("cognitio:responses", args=[self.ev.pk]), data)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(QuestionResponse.objects.count(), 4)  # Caio com 9 de 2 recusado
        e1 = SkillEvidence.objects.get(student=self.ana, item=self.h1)
        self.assertEqual((e1.ratio, e1.weight, e1.source_type), (1.0, 1.0, "questao"))
        sec = SkillEvidence.objects.get(student=self.ana, item__code="EF06MA02")
        self.assertEqual(sec.weight, 0.5)
        e2 = SkillEvidence.objects.get(student=self.ana, item=self.h2)
        self.assertEqual((e2.ratio, e2.error_type), (0.25, "conceitual"))
        absent = SkillEvidence.objects.get(student=self.bia, item=self.h1)
        self.assertEqual((absent.ratio, absent.no_evidence_reason), (None, "ausente"))
        self.assertEqual(Grade.objects.get(student=self.ana).value, Decimal("6.3"))  # 2,5 de 4 → 6,25 → 6,3 (arredonda para cima)
        self.assertFalse(Grade.objects.filter(student=self.bia).exists())  # ausente não ganha zero
        self.login(self.prof_b)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_existing_records_become_evidence_automatically(self):
        self.ev.curriculum.add(self.h1)
        self.ev.status = "publicada"
        self.ev.save()
        act = Activity.objects.create(school=self.school, class_group=self.cg, subject=self.mat, title="Lista",
                                      class_date=self.today, created_by=self.prof, status="publicada")
        act.curriculum.add(self.h2)
        with self.captureOnCommitCallbacks(execute=True):
            Grade.objects.create(school=self.school, evaluation=self.ev, student=self.ana, value=8)
            Submission.objects.create(school=self.school, activity=act, student=self.ana, status="entregue", grade=5)
            Submission.objects.create(school=self.school, activity=act, student=self.bia, status="nao_entregue")
        g = SkillEvidence.objects.get(student=self.ana, item=self.h1)
        self.assertEqual((g.source_type, g.ratio, g.weight), ("avaliacao", 0.8, 0.5))
        a = SkillEvidence.objects.get(student=self.ana, item=self.h2)
        self.assertEqual((a.source_type, a.ratio, a.weight), ("atividade", 0.5, 0.7))
        nd = SkillEvidence.objects.get(student=self.bia, item=self.h2)
        self.assertEqual((nd.ratio, nd.no_evidence_reason), (None, "não entregue"))
        # Rebuild é idempotente e remove o que deixou de existir.
        act.curriculum.remove(self.h2)
        rebuild_class(self.cg)
        self.assertFalse(SkillEvidence.objects.filter(item=self.h2).exists())

    def test_observation_for_several_students(self):
        self.login(self.prof)
        url = reverse("cognitio:observation_create", args=[self.cg.pk, self.mat.pk])
        r = self.client.post(url, {"item": self.h1.pk, "level": 4, "context": "Resolução no quadro",
                                   "observed_on": self.today.isoformat(), "students": [self.ana.pk, self.bia.pk]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SkillObservation.objects.count(), 2)
        self.assertEqual(SkillEvidence.objects.filter(source_type="observacao", ratio=0.75).count(), 2)
        self.login(self.prof_geo)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_batch_with_individual_review_and_who_is_missing(self):
        """Prompt 18 §7: nível de todos, ajuste por estudante antes de confirmar, e quem falta registrar."""
        self.login(self.prof)
        url = reverse("cognitio:observation_create", args=[self.cg.pk, self.mat.pk])
        r = self.client.post(url, {"item": self.h1.pk, "level": 4, "context": "Resolução no quadro",
                                   "observed_on": self.today.isoformat(),
                                   "students": [self.ana.pk, self.bia.pk, self.caio.pk],
                                   f"lv_{self.bia.pk}": "2", f"lv_{self.caio.pk}": ""})
        self.assertEqual(r.status_code, 302)
        levels = dict(SkillObservation.objects.values_list("student__first_name", "level"))
        self.assertEqual(levels, {"Ana": 4, "Bia": 2, "Caio": 4})
        self.assertTrue(AuditLog.objects.filter(detail__endswith="1 com nível próprio").exists())
        # Nível próprio inválido é recusado e nada é gravado.
        before = SkillObservation.objects.count()
        r = self.client.post(url, {"item": self.h1.pk, "level": 4, "context": "x", "observed_on": self.today.isoformat(),
                                   "students": [self.ana.pk], f"lv_{self.ana.pk}": "9"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(SkillObservation.objects.count(), before)
        # Situação da turma na habilidade: uma observação só ainda não é registro suficiente.
        page = self.client.get(url + f"?item={self.h2.pk}")
        self.assertContains(page, "3 estudantes ainda sem registro suficiente em EF06MA03.")
        self.assertContains(page, "<strong>Não avaliada</strong>", count=3)
        page = self.client.get(url + f"?item={self.h1.pk}&estudante={self.bia.pk}")
        self.assertContains(page, "Sem evidência suficiente")
        self.assertContains(page, f'value="{self.bia.pk}" id="obs-{self.bia.pk}" checked')


class MapAccessTests(Base):
    def setUp(self):
        super().setUp()
        for st, r in ((self.ana, 2), (self.ana, 3), (self.bia, 2), (self.bia, 1), (self.caio, 5), (self.caio, 5)):
            SkillObservation.objects.create(school=self.school, student=st, item=self.h1, class_group=self.cg,
                                            subject=self.mat, teacher=self.prof, level=r, context="Sala")
        geo_item = CurriculumItem.objects.get(code="EF06GE01")
        SkillObservation.objects.create(school=self.school, student=self.ana, item=geo_item, class_group=self.cg,
                                        subject=self.geo, teacher=self.prof_geo, level=1, context="Mapa")
        rebuild_class(self.cg)

    def test_student_map_scope(self):
        url = reverse("cognitio:student_map", args=[self.ana.pk])
        self.login(self.prof)
        r = self.client.get(url + f"?habilidade={self.h1.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "EF06MA01")
        self.assertNotContains(r, "EF06GE01")  # disciplina do colega
        self.assertContains(r, "Evidências consideradas")
        self.assertTrue(AuditLog.objects.filter(user=self.prof, action="view", target_type="Student").exists())
        self.login(self.coord)
        r = self.client.get(url)
        self.assertContains(r, "EF06GE01")
        for user in (self.prof_b, self.coord_b, self.sec, self.fam):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, 403, user.username)

    def test_class_view_groups_and_focus(self):
        self.login(self.prof)
        url = reverse("cognitio:class_view", args=[self.cg.pk])
        r = self.client.get(url + f"?habilidade={self.h1.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([s["item"].code for s in r.context["retake"]], ["EF06MA01"])
        self.assertEqual([st.first_name for st, a in r.context["focus"]["rows"]][:2], ["Bia", "Ana"])
        self.assertEqual(r.context["subject"], self.mat)
        self.assertEqual([g["item"].code for g in r.context["groups"]], ["EF06MA01"])
        r = self.client.get(url + f"?disciplina={self.geo.pk}")
        self.assertEqual(r.context["subject"], self.mat)  # não leciona Geografia: volta para a dele
        self.login(self.prof_b)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_scale_settings(self):
        self.login(self.prof)
        self.assertEqual(self.client.get(reverse("cognitio:scale")).status_code, 403)
        self.login(self.coord)
        r = self.client.post(reverse("cognitio:scale"), {"t1": "0.6", "t2": "0.5", "t3": "0.8", "min_evidence": 2,
                                                          "min_weight": "1.2", "half_life_days": 120, "stale_days": 60})
        self.assertEqual(r.status_code, 200)
        self.client.post(reverse("cognitio:scale"), {"t1": "0.3", "t2": "0.5", "t3": "0.7", "min_evidence": 2,
                                                      "min_weight": "1.2", "half_life_days": 90, "stale_days": 60})
        self.assertEqual(float(MasteryScale.objects.get().t3), 0.7)
        self.login(self.prof)
        r = self.client.get(reverse("cognitio:home"))
        self.assertContains(r, "6º Ano A · Matemática")


class CssNamesTests(TestCase):
    def test_state_classes_do_not_collide_with_bootstrap_utilities(self):
        import re

        from apps.cognitio.mastery import CSS

        # .m-1 a .m-5 são margens do Bootstrap: usar esses nomes estragava o layout das legendas.
        for css in CSS.values():
            self.assertIsNone(re.fullmatch(r"[mp][trblxyse]?-(\d|auto)", css), css)
