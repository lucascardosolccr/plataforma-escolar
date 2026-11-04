"""Seletor de habilidades sob demanda: formulário leve para quem leciona muitos componentes e anos, sem
nunca esconder uma habilidade já marcada."""

import re

from django.urls import reverse

from apps.academics.models import ClassGroup, Subject, TeacherAssignment
from apps.communication.tests.test_communication import CommunicationBase
from apps.curriculum.forms import LAZY_MIN
from apps.curriculum.models import CurriculumItem
from apps.pedagogy.models import Activity


class PickerBase(CommunicationBase):
    def setUp(self):
        super().setUp()
        port = Subject.objects.create(school=self.school, name="Língua Portuguesa")
        for n in range(2, 10):
            cg = ClassGroup.objects.create(school=self.school, school_year=self.year, name=f"{n}º Ano A")
            for subject in (self.mat, port):
                TeacherAssignment.objects.create(school=self.school, school_year=self.year, teacher=self.prof,
                                                 class_group=cg, subject=subject)
        self.client.force_login(self.prof)


class LazyPickerTests(PickerBase):
    def boxes(self, html):
        return re.findall(r'name="curriculum" value="(\d+)"', html)

    def test_big_picker_arrives_empty_and_groups_load_on_demand(self):
        html = self.client.get(reverse("pedagogy:activity_create")).content.decode()
        urls = re.findall(r'data-lazy-group="([^"]+)"', html)
        self.assertGreater(len(urls), 10)
        self.assertLess(len(self.boxes(html)), LAZY_MIN)  # só os grupos pequenos/gerais vêm prontos
        part = self.client.get(urls[0].replace("&amp;", "&"))
        self.assertGreater(len(self.boxes(part.content.decode())), 0)
        self.client.force_login(self.resp)
        self.assertEqual(self.client.get(urls[0].replace("&amp;", "&")).status_code, 403)

    def test_selected_skill_is_never_hidden_when_editing(self):
        item = CurriculumItem.objects.filter(school__isnull=True, code__startswith="EF05MA").first()
        act = Activity.objects.create(school=self.school, class_group=self.turma, subject=self.mat, title="X",
                                      created_by=self.prof)
        act.curriculum.add(item)
        # Na edição a turma está definida (foco): a lista é a da turma e o item marcado aparece marcado.
        edit = self.client.get(reverse("pedagogy:activity_edit", args=[act.pk])).content.decode()
        self.assertIn(f'value="{item.pk}" id=', edit)
        self.assertRegex(edit, rf'value="{item.pk}" id="[^"]+" checked')

    def test_bound_form_keeps_the_group_with_a_choice(self):
        from apps.pedagogy.forms import ActivityForm

        item = CurriculumItem.objects.filter(school__isnull=True, code__startswith="EF07MA").first()
        from django.utils.datastructures import MultiValueDict

        form = ActivityForm(data=MultiValueDict({"curriculum": [str(item.pk)]}), user=self.prof)
        full = [label for label, items in form.curriculum_groups if any(i.pk == item.pk for i in items)]
        self.assertTrue(full)  # o grupo com a escolha veio completo...
        self.assertNotIn(full[0], form.curriculum_lazy)  # ...e não sob demanda
        self.assertTrue(form.curriculum_lazy)  # os demais grupos grandes, sim


class FocusedEvidenceFormTests(PickerBase):
    def test_coming_from_a_class_lists_only_that_class_and_component(self):
        cg = self.turma
        url = reverse("curriculum:evidence_create") + f"?par={cg.pk}:{self.mat.pk}"
        page = self.client.get(url)
        form = page.context["form"]
        self.assertEqual([v for v, _ in form.fields["pair"].choices], [f"{cg.pk}:{self.mat.pk}"])
        labels = [label for label, _ in form.fields["item"].choices[1:]]
        self.assertTrue(labels and all(lb.startswith("Matemática") or lb.startswith("Competências") for lb in labels))
        self.assertContains(page, "Escolher outra turma ou disciplina")
        full = self.client.get(reverse("curriculum:evidence_create")).context["form"]
        self.assertGreater(len(full.fields["pair"].choices), 1)  # sem par: todas as turmas, como antes
