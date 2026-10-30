"""Tela de atividades da família: filtro, resumo por situação e "nova".

O filtro de situação só aparecia com mais de um filho (``children|length >
1``): o responsável de um filho só e a conta do estudante nunca conseguiam
separar o que está a vencer do que já encerrou. A §6.3 pede também que as
tarefas novas sejam fáceis de identificar.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.core.models import Role

from ..models import Activity, GroupWork
from .test_group_work import GroupWorkBase
from .test_pedagogy import PedagogyBase, User


class FamilyActivityFilterTests(PedagogyBase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()

    def _act(self, title, published_ago, deadline_in=None, **extra):
        return Activity.objects.create(
            school=self.school,
            class_group=self.turma,
            subject=self.mat,
            title=title,
            created_by=self.prof,
            status=extra.pop("status", Activity.Status.PUBLISHED),
            published_date=self.today - timedelta(days=published_ago),
            deadline=(
                self.today + timedelta(days=deadline_in)
                if deadline_in is not None
                else None
            ),
            **extra,
        )

    def _cenario(self):
        self._act("Vence amanhã", published_ago=10, deadline_in=1)
        self._act("Vence em dez dias", published_ago=10, deadline_in=10)
        self._act("Já encerrou", published_ago=10, deadline_in=-2)
        self._act("Publicada hoje", published_ago=0, deadline_in=7)

    def test_single_child_guardian_sees_situation_filter(self):
        self._cenario()
        self.login("resp")  # um filho só (Ana)
        resp = self.client.get(reverse("pedagogy:activity_list"))
        self.assertRegex(resp.content.decode(), r'class="summary-pill[^"]*"|href="[^"]*\?situacao=')
        self.assertContains(resp, "?situacao=")

    def test_student_account_sees_situation_filter(self):
        conta = User.objects.create_user(
            username="aluna", password="senha-forte-1", role=Role.ESTUDANTE,
            school=self.school,
        )
        self.ana.user = conta
        self.ana.save(update_fields=["user"])
        self._cenario()
        self.login("aluna")
        resp = self.client.get(reverse("pedagogy:activity_list"))
        self.assertRegex(resp.content.decode(), r'class="summary-pill[^"]*"|href="[^"]*\?situacao=')
        self.assertContains(resp, "?situacao=")
        self.assertContains(resp, "Publicada hoje")

    def test_summary_counts_by_situation(self):
        self._cenario()
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:activity_list"))
        resumo = {s["key"]: s["count"] for s in resp.context["summary"]}
        self.assertEqual(resumo["a_vencer"], 1)
        self.assertEqual(resumo["pendente"], 2)  # dez dias + publicada hoje
        self.assertEqual(resumo["encerrada"], 1)
        self.assertEqual(resumo["nova"], 1)

    def test_new_filter_shows_only_recent_publications(self):
        self._cenario()
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:activity_list"), {"situacao": "nova"})
        self.assertContains(resp, "Publicada hoje")
        self.assertNotContains(resp, "Vence amanhã")
        self.assertNotContains(resp, "Já encerrou")

    def test_new_badge_marks_recent_activity(self):
        self._cenario()
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:activity_list"))
        novas = [r for r in resp.context["rows"] if r["is_new"]]
        self.assertEqual([r["activity"].title for r in novas], ["Publicada hoje"])
        self.assertContains(resp, "badge-new")

    def test_canceled_is_never_new(self):
        self._act(
            "Cancelada hoje",
            published_ago=0,
            deadline_in=5,
            status=Activity.Status.CANCELED,
            visible_before_cancel=True,
        )
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:activity_list"))
        self.assertEqual([r["is_new"] for r in resp.context["rows"]], [False])

    def test_summary_respects_child_filter(self):
        """Contagem por filho: a Beatriz (outra turma) não soma na da Ana."""
        from apps.registry.models import GuardianLink

        GuardianLink.objects.create(
            school=self.school, guardian=self.resp, student=self.bea, status="aprovado"
        )
        self._cenario()
        Activity.objects.create(
            school=self.school, class_group=self.turma_b, subject=self.port,
            title="Da Beatriz", created_by=self.prof2,
            published_date=self.today - timedelta(days=5),
            deadline=self.today + timedelta(days=1),
        )
        self.login("resp")
        resp = self.client.get(
            reverse("pedagogy:activity_list"), {"estudante": self.ana.pk}
        )
        resumo = {s["key"]: s["count"] for s in resp.context["summary"]}
        self.assertEqual(resumo["a_vencer"], 1)
        self.assertNotContains(resp, "Da Beatriz")

    def test_unknown_situation_is_ignored(self):
        self._cenario()
        self.login("resp")
        resp = self.client.get(reverse("pedagogy:activity_list"), {"situacao": "xyz"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["state"])
        self.assertEqual(len(resp.context["rows"]), 4)


class FamilyGroupWorkFilterTests(GroupWorkBase):
    def test_single_child_guardian_sees_filter_and_summary(self):
        hoje = timezone.localdate()
        work = self.make_work(
            title="Maquete", published_date=hoje, deadline=hoje + timedelta(days=1)
        )
        self.make_group(work, "Grupo 1", [self.ana, self.bruno])
        self.login("resp_ana")
        resp = self.client.get(reverse("pedagogy:group_work_list"))
        self.assertRegex(resp.content.decode(), r'class="summary-pill[^"]*"|href="[^"]*\?situacao=')
        self.assertContains(resp, "?situacao=")
        resumo = {s["key"]: s["count"] for s in resp.context["summary"]}
        self.assertEqual(resumo, {"nova": 1, "a_vencer": 1})
        self.assertEqual(work.status, GroupWork.Status.PUBLISHED)


class TeacherListLinksTests(PedagogyBase):
    """Todo link da lista do professor abre para ele.

    O acesso do professor a uma atividade passou a exigir o par turma +
    disciplina. A lista precisa seguir a mesma regra: mostrar a atividade de
    outra disciplina da mesma turma levava a um "Ver" que respondia 403.
    """

    def test_every_activity_in_teacher_list_opens(self):
        from apps.academics.models import TeacherAssignment

        # prof2 também leciona Português na turma da Ana (prof leciona Matemática).
        TeacherAssignment.objects.create(
            school=self.school, school_year=self.year, teacher=self.prof2,
            class_group=self.turma, subject=self.port,
        )
        Activity.objects.create(
            school=self.school, class_group=self.turma, subject=self.port,
            title="Redação de Português", created_by=self.prof2,
        )
        Activity.objects.create(
            school=self.school, class_group=self.turma, subject=self.mat,
            title="Lista de frações", created_by=self.prof,
        )
        self.login("prof")
        resp = self.client.get(reverse("pedagogy:activity_list"))
        titulos = [r["activity"].title for r in resp.context["rows"]]
        self.assertIn("Lista de frações", titulos)
        for r in resp.context["rows"]:
            with self.subTest(atividade=r["activity"].title):
                detalhe = self.client.get(
                    reverse("pedagogy:activity_detail", args=[r["activity"].pk])
                )
                self.assertEqual(detalhe.status_code, 200)

    def test_student_record_links_open_for_teacher(self):
        """Na ficha do estudante, o professor só vê o que consegue abrir."""
        from apps.academics.models import TeacherAssignment

        TeacherAssignment.objects.create(
            school=self.school, school_year=self.year, teacher=self.prof2,
            class_group=self.turma, subject=self.port,
        )
        outra = Activity.objects.create(
            school=self.school, class_group=self.turma, subject=self.port,
            title="Redação de Português", created_by=self.prof2,
        )
        Activity.objects.create(
            school=self.school, class_group=self.turma, subject=self.mat,
            title="Lista de frações", created_by=self.prof,
        )
        self.login("prof")
        resp = self.client.get(reverse("student_detail", args=[self.ana.pk]))
        titulos = [r["activity"].title for r in resp.context["activity_rows"]]
        self.assertEqual(titulos, ["Lista de frações"])
        self.assertNotContains(resp, reverse("pedagogy:activity_detail", args=[outra.pk]))
