"""Integração curricular: catálogo BNCC, vínculos, evidências, indicadores e referências (Prompt 15)."""

from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
from apps.coordination.models import CoordinatorAssignment
from apps.core.models import AuditLog, Role, School, User
from apps.curriculum import services
from apps.curriculum.models import CurriculumItem, LearningEvidence, NormativeReference, component_for, year_for
from apps.pedagogy.models import Activity, Evaluation, LessonPlan
from apps.registry.models import Enrollment, GuardianLink, Student

PW = "Senha-forte-123"


class Base(TestCase):
    coordenacao_restrita = True

    def setUp(self):
        self.today = timezone.localdate()
        self.school = School.objects.create(name="Escola", code="e")
        self.year = SchoolYear.objects.create(school=self.school, name=str(self.today.year), is_current=True,
                                              start_date=date(self.today.year, 1, 1),
                                              end_date=date(self.today.year, 12, 31))
        self.a = ClassGroup.objects.create(school=self.school, school_year=self.year, name="6º Ano A")
        self.b = ClassGroup.objects.create(school=self.school, school_year=self.year, name="6º Ano B")
        self.mat = Subject.objects.create(school=self.school, name="Matemática")
        self.port = Subject.objects.create(school=self.school, name="Português")
        mk = lambda u, r: User.objects.create_user(u, password=PW, role=r, school=self.school, first_name=u.title())
        self.prof = mk("prof", Role.PROFESSOR)
        self.prof2 = mk("prof2", Role.PROFESSOR)
        self.coord = mk("coord", Role.COORDENACAO)
        self.sec = mk("sec", Role.SECRETARIA)
        self.dir = mk("dir", Role.DIRECAO)
        self.fam = mk("fam", Role.RESPONSAVEL)
        TeacherAssignment.objects.create(school=self.school, school_year=self.year, teacher=self.prof,
                                         class_group=self.a, subject=self.mat)
        TeacherAssignment.objects.create(school=self.school, school_year=self.year, teacher=self.prof2,
                                         class_group=self.b, subject=self.port)
        d = CoordinatorAssignment.objects.create(school=self.school, coordinator=self.coord, starts_on=self.today)
        d.class_groups.add(self.a)
        self.ana = Student.objects.create(school=self.school, first_name="Ana")
        Enrollment.objects.create(school=self.school, student=self.ana, class_group=self.a, school_year=self.year)
        GuardianLink.objects.create(school=self.school, guardian=self.fam, student=self.ana, status="aprovado")
        self.h1 = CurriculumItem.objects.get(school__isnull=True, code="EF06MA01")
        self.h2 = CurriculumItem.objects.get(school__isnull=True, code="EF06MA02")
        self.h3 = CurriculumItem.objects.get(school__isnull=True, code="EF06MA03")

    def login(self, user):
        self.client.logout()
        self.client.login(username=user.username, password=PW)


class CatalogTests(Base):
    def test_bncc_loaded_from_official_text(self):
        skills = CurriculumItem.objects.filter(school__isnull=True, kind="habilidade").exclude(component="Computação")
        self.assertEqual(skills.count(), 1304)  # BNCC 2018; Computação (complemento de 2022) em test_computacao
        self.assertEqual(CurriculumItem.objects.filter(kind="competencia_geral").count(), 10)
        self.assertTrue(self.h1.text.startswith("Comparar, ordenar, ler e escrever números naturais"))
        self.assertEqual(CurriculumItem.objects.get(code="EF69AR01").year_list, [6, 7, 8, 9])
        self.assertEqual(CurriculumItem.objects.get(code="EF15LP01").year_list, [1, 2, 3, 4, 5])
        self.assertTrue(CurriculumItem.objects.get(code="CG10").text.endswith("inclusivos, sustentáveis e solidários."))
        self.assertTrue(all(i.source_url.startswith("https://basenacionalcomum.mec.gov.br") for i in skills[:5]))

    def test_component_and_year_inference(self):
        self.assertEqual(component_for(self.port), "Língua Portuguesa")
        self.assertEqual(component_for(Subject(name="Educação Física")), "Educação Física")
        self.assertEqual(component_for(Subject(name="Robótica")), "")
        self.assertEqual(component_for(Subject(name="Robótica", curriculum_component="Matemática")), "Matemática")
        self.assertEqual(year_for(self.a), 6)
        self.assertEqual(year_for(ClassGroup(name="Turma X", grade="9º ano")), 9)
        self.assertIsNone(year_for(ClassGroup(name="Multisseriada")))

    def test_catalog_access_and_search(self):
        self.login(self.prof)
        r = self.client.get(reverse("curriculum:catalog") + "?q=EF06MA0&componente=Matemática")
        self.assertEqual(r.status_code, 200)
        codes = [i.code for i in r.context["page"]]
        self.assertIn("EF06MA01", codes)
        self.assertTrue(all(c.startswith("EF06MA0") for c in codes))
        r = self.client.get(reverse("curriculum:catalog") + "?ano=6&componente=Arte")
        self.assertIn("EF69AR01", [i.code for i in r.context["page"].paginator.object_list])
        for user in (self.fam, self.sec):
            self.login(user)
            self.assertEqual(self.client.get(reverse("curriculum:catalog")).status_code, 403)

    def test_picker_groups_by_pair(self):
        groups = dict(services.picker_groups(self.prof))
        self.assertIn("Matemática — 6º ano", groups)
        self.assertIn(self.h1, groups["Matemática — 6º ano"])
        self.assertNotIn("Língua Portuguesa — 6º ano", groups)  # não é par do prof
        self.assertEqual(len(groups["Competências gerais da BNCC"]), 10)


class LinkTests(Base):
    def test_activity_saves_selected_and_typed_codes(self):
        self.login(self.prof)
        url = reverse("pedagogy:activity_create")
        form = self.client.get(url).context["form"]
        self.assertTrue(any(label.startswith("Matemática") for label, _ in form.curriculum_groups))
        data = {"class_group": self.a.pk, "subject": self.mat.pk, "title": "Reta numérica",
                "class_date": self.today.isoformat(), "published_date": self.today.isoformat(),
                "description": "Exercícios", "curriculum": [self.h1.pk], "curriculum_codes": "ef06ma02, EF67EF01"}
        r = self.client.post(url, data)
        self.assertEqual(r.status_code, 302)
        act = Activity.objects.get(title="Reta numérica")
        self.assertEqual(set(act.curriculum.values_list("code", flat=True)), {"EF06MA01", "EF06MA02", "EF67EF01"})
        # Código inexistente: erro claro, nada salvo.
        data.update(title="Outra", curriculum_codes="EF99XX99")
        r = self.client.post(url, data)
        self.assertEqual(r.status_code, 200)
        self.assertIn("EF99XX99", str(r.context["form"].errors))
        self.assertFalse(Activity.objects.filter(title="Outra").exists())
        # A família vê os códigos na atividade publicada.
        self.client.post(reverse("pedagogy:activity_edit", args=[act.pk]),
                         {**data, "title": "Reta numérica", "curriculum_codes": "", "curriculum": [self.h1.pk],
                          "_publish": "1"})
        self.login(self.fam)
        r = self.client.get(reverse("pedagogy:activity_detail", args=[act.pk]))
        self.assertContains(r, "EF06MA01")

    def test_plan_and_evaluation_links_and_duplicate_keeps_codes(self):
        self.login(self.prof)
        monday = self.today - timedelta(days=self.today.weekday())
        r = self.client.post(reverse("pedagogy:lessonplan_create"), {
            "class_group": self.a.pk, "subject": self.mat.pk, "starts_on": monday.isoformat(),
            "ends_on": (monday + timedelta(days=4)).isoformat(), "title": "Números", "content": "c",
            "objectives": "o", "curriculum": [self.h1.pk, self.h2.pk]})
        self.assertEqual(r.status_code, 302)
        plan = LessonPlan.objects.get()
        self.assertEqual(plan.curriculum.count(), 2)
        self.client.post(reverse("pedagogy:lessonplan_duplicate", args=[plan.pk]))
        self.assertEqual(LessonPlan.objects.exclude(pk=plan.pk).get().curriculum.count(), 2)
        self.client.post(reverse("pedagogy:evaluation_create"), {
            "class_group": self.a.pk, "subject": self.mat.pk, "title": "P1", "kind": "", "weight": "1",
            "date": self.today.isoformat(), "description": "", "curriculum": [self.h3.pk]})
        self.assertEqual(list(Evaluation.objects.get().curriculum.values_list("code", flat=True)), ["EF06MA03"])


class CoverageTests(Base):
    def setUp(self):
        super().setUp()
        past = self.today - timedelta(days=20)
        plan = LessonPlan.objects.create(school=self.school, teacher=self.prof, class_group=self.a, subject=self.mat,
                                         starts_on=past, ends_on=past + timedelta(days=4), title="P", content="c",
                                         objectives="o")
        plan.curriculum.set([self.h1, self.h2])
        act = Activity.objects.create(school=self.school, class_group=self.a, subject=self.mat, title="A",
                                      class_date=self.today - timedelta(days=1), published_date=self.today,
                                      created_by=self.prof, status="publicada")
        act.curriculum.set([self.h1])
        ev = Evaluation.objects.create(school=self.school, class_group=self.a, subject=self.mat, title="P1",
                                       date=self.today, created_by=self.prof)
        ev.curriculum.set([self.h3])
        LearningEvidence.objects.create(school=self.school, class_group=self.a, subject=self.mat, item=self.h3,
                                        teacher=self.prof, observed_on=self.today, judgement="retomada",
                                        description="Erros de cálculo mental.")

    def test_indicators(self):
        data = services.coverage(self.a, self.mat)
        c = data["counts"]
        self.assertEqual((c["planned"], c["worked"], c["assessed"], c["evidenced"], c["retake"], c["not_done"]),
                         (2, 1, 1, 1, 1, 1))
        self.assertEqual([i.code for i in data["not_done"]], ["EF06MA02"])  # planejada e não executada
        self.assertEqual([i.code for i in data["retake"]], ["EF06MA03"])
        gap_codes = {i.code for i in data["gaps"]}
        self.assertNotIn("EF06MA01", gap_codes)
        self.assertIn("EF06MA04", gap_codes)
        self.assertEqual(data["evolution"][-1]["total"], 2)  # MA01 (atividade) e MA03 (avaliação/evidência)

    def test_access_by_pair(self):
        url = reverse("curriculum:coverage")
        self.login(self.prof)
        r = self.client.get(url)
        self.assertEqual(r.context["pair"], (self.a, self.mat))
        self.assertContains(r, "Precisam de retomada (1)")
        self.assertEqual(self.client.get(url + f"?par={self.b.pk}:{self.port.pk}").status_code, 403)
        self.login(self.coord)  # coordenação designada só para o 6º A
        self.assertEqual(self.client.get(url + f"?par={self.a.pk}:{self.mat.pk}").status_code, 200)
        self.assertEqual(self.client.get(url + f"?par={self.b.pk}:{self.port.pk}").status_code, 403)
        self.login(self.dir)
        self.assertEqual(self.client.get(url + f"?par={self.b.pk}:{self.port.pk}").status_code, 200)
        for user in (self.fam, self.sec):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_evidence_create_validates_pair(self):
        self.login(self.prof)
        url = reverse("curriculum:evidence_create")
        other = Activity.objects.create(school=self.school, class_group=self.a, subject=self.port, title="X",
                                        class_date=self.today, created_by=self.prof)
        r = self.client.post(url, {"pair": f"{self.a.pk}:{self.mat.pk}", "item": self.h1.pk,
                                   "observed_on": self.today.isoformat(), "judgement": "consolidada",
                                   "description": "Leram a reta.", "activity": other.pk})
        self.assertEqual(r.status_code, 200)
        self.assertIn("activity", r.context["form"].errors)
        r = self.client.post(url, {"pair": f"{self.b.pk}:{self.port.pk}", "item": self.h1.pk,
                                   "observed_on": self.today.isoformat(), "judgement": "consolidada",
                                   "description": "x"})
        self.assertIn("pair", r.context["form"].errors)
        r = self.client.post(url, {"pair": f"{self.a.pk}:{self.mat.pk}", "item": self.h1.pk,
                                   "observed_on": self.today.isoformat(), "judgement": "consolidada",
                                   "description": "Leram a reta."})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(AuditLog.objects.filter(action="create", target_type="LearningEvidence").exists())
        self.login(self.coord)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_evidence_form_lists_only_the_teachers_components_and_the_chosen_item(self):
        """Antes eram todas as habilidades visíveis (milhares de opções); agora, os grupos do componente e do
        ano das turmas do professor, como nos formulários de atividade e prova."""
        other_year = CurriculumItem.objects.get(school__isnull=True, code="EF09MA01")
        self.login(self.prof)
        url = reverse("curriculum:evidence_create")
        form = self.client.get(url).context["form"]
        ids = set(form.fields["item"].queryset.values_list("pk", flat=True))
        self.assertIn(self.h1.pk, ids)
        self.assertNotIn(other_year.pk, ids)
        self.assertFalse(CurriculumItem.objects.filter(pk__in=ids, component="Geografia").exists())
        # vindo de um link com a habilidade escolhida, ela aparece mesmo fora dos grupos
        form = self.client.get(url, {"item": other_year.pk}).context["form"]
        self.assertIn(other_year.pk, set(form.fields["item"].queryset.values_list("pk", flat=True)))
        r = self.client.post(url, {"pair": f"{self.a.pk}:{self.mat.pk}", "item": other_year.pk,
                                   "observed_on": self.today.isoformat(), "judgement": "desenvolvimento",
                                   "description": "Retomada com o 9º ano."})
        self.assertEqual(r.status_code, 302)


class LocalItemsAndReferencesTests(Base):
    def test_import_csv_by_coordination(self):
        url = reverse("curriculum:item_import")
        self.login(self.prof)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login(self.coord)
        csv_text = ("tipo;codigo;componente;anos;texto;fonte;url;habilidades_bncc\n"
                    "objetivo_df;DF-MA6-01;Matemática;6;Ler números naturais;Currículo em Movimento, p. 1;;EF06MA01\n"
                    "errado;X;;;;;;\n")
        r = self.client.post(url, {"file": SimpleUploadedFile("c.csv", csv_text.encode("utf-8"))})
        self.assertEqual(r.context["report"]["created"], 1)
        self.assertEqual(len(r.context["report"]["errors"]), 1)
        item = CurriculumItem.objects.get(school=self.school, code="DF-MA6-01")
        self.assertEqual(list(item.bncc.values_list("code", flat=True)), ["EF06MA01"])
        # Reimportar atualiza, não duplica.
        self.client.post(url, {"file": SimpleUploadedFile("c.csv", csv_text.encode("utf-8"))})
        self.assertEqual(CurriculumItem.objects.filter(school=self.school).count(), 1)
        # Aparece no seletor do professor de Matemática do 6º ano.
        groups = dict(services.picker_groups(self.prof))
        self.assertIn(item, groups["Matemática — 6º ano · Currículo em Movimento: objetivos"])
        # Outra escola não vê o item local.
        other = School.objects.create(name="Outra", code="o")
        self.assertFalse(CurriculumItem.objects.filter(CurriculumItem.visible_q(other), pk=item.pk).exists())

    def test_references_page(self):
        self.assertGreaterEqual(NormativeReference.objects.count(), 20)
        p421 = NormativeReference.objects.get(name="Portaria MEC nº 421/2026", provision__startswith="Art. 7º")
        self.assertIn("não poderá estar condicionada à exigência de diagnóstico", p421.excerpt)
        for user in (self.prof, self.sec, self.dir):
            self.login(user)
            r = self.client.get(reverse("curriculum:references") + "?natureza=legal")
            self.assertEqual(r.status_code, 200)
            self.assertTrue(all(ref.nature == "legal" for ref in r.context["refs"]))
        self.login(self.fam)
        self.assertEqual(self.client.get(reverse("curriculum:references")).status_code, 403)


class DataQualityTests(Base):
    def test_unmapped_subjects_and_classes_are_listed(self):
        robo = Subject.objects.create(school=self.school, name="Robótica")
        multi = ClassGroup.objects.create(school=self.school, school_year=self.year, name="Multisseriada")
        TeacherAssignment.objects.create(school=self.school, school_year=self.year, teacher=self.prof,
                                         class_group=multi, subject=robo)
        self.login(self.dir)
        r = self.client.get(reverse("analytics:data_quality"))
        self.assertEqual(r.status_code, 200)
        q = r.context["q"]
        self.assertEqual([s.name for s in q["subjects_no_component"]], ["Robótica"])
        self.assertEqual([c.name for c in q["classes_no_year"]], ["Multisseriada"])
        # Informar o componente no cadastro resolve.
        robo.curriculum_component = "Matemática"
        robo.save()
        r = self.client.get(reverse("analytics:data_quality"))
        self.assertEqual(r.context["q"]["subjects_no_component"], [])


class PickerFocusTests(Base):
    """Com a turma definida, o seletor mostra só as habilidades dela (um professor de muitas turmas recebia
    centenas de KB); o que já estava marcado continua visível e "Outros códigos" aceita qualquer código."""

    def setUp(self):
        super().setUp()
        from apps.academics.models import TeacherAssignment

        self.c1 = ClassGroup.objects.create(school=self.school, school_year=self.year, name="1º Ano C")
        TeacherAssignment.objects.create(school=self.school, school_year=self.year, teacher=self.prof,
                                         class_group=self.c1, subject=self.mat)

    def test_new_activity_from_a_class_and_edit_show_only_that_class(self):
        self.login(self.prof)
        url = reverse("pedagogy:activity_create")
        all_labels = [label for label, _ in self.client.get(url).context["form"].curriculum_groups]
        self.assertIn("Matemática — 1º ano", all_labels)
        self.assertIn("Matemática — 6º ano", all_labels)
        page = self.client.get(url + f"?turma={self.c1.pk}")
        labels = [label for label, _ in page.context["form"].curriculum_groups]
        self.assertIn("Matemática — 1º ano", labels)
        self.assertNotIn("Matemática — 6º ano", labels)
        self.assertContains(page, "Mostrando as habilidades da turma escolhida")
        act = Activity.objects.create(school=self.school, class_group=self.c1, subject=self.mat, title="Contagem",
                                      created_by=self.prof, class_date=self.today)
        act.curriculum.add(self.h1)  # habilidade do 6º ano marcada antes: continua visível
        form = self.client.get(reverse("pedagogy:activity_edit", args=[act.pk])).context["form"]
        groups = dict(form.curriculum_groups)
        self.assertNotIn("Matemática — 6º ano", groups)
        self.assertIn(self.h1, groups["Já selecionados"])
