"""Terceira rodada de busca de melhorias (30/10/2026).

Cada teste aqui reprovou no código anterior à correção que ele cobre.
"""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.academics.models import SchoolYear
from apps.core.models import Role
from apps.core.tests.test_redesign_round2 import Round2Base
from apps.pedagogy.models import Occurrence
from apps.registry.models import Student


class SchoolYearFormSideEffectTests(Round2Base):
    """Marcar "ano letivo atual" num formulário recusado não pode desmarcar o
    ano atual de verdade: a escola ficaria sem ano corrente."""

    def test_invalid_form_keeps_current_year(self):
        atual = SchoolYear.objects.get(school=self.school)
        atual.is_current = True
        atual.save()
        self.login(self.users[Role.ADMIN])
        resp = self.client.post(reverse("school_year_create"), {
            "name": "2027", "start_date": "2027-12-01", "end_date": "2027-02-01", "is_current": "on",
        })
        self.assertEqual(resp.status_code, 200)  # recusado: fim antes do início
        atual.refresh_from_db()
        self.assertTrue(atual.is_current)

    def test_valid_form_moves_current_year(self):
        atual = SchoolYear.objects.get(school=self.school)
        atual.is_current = True
        atual.save()
        self.login(self.users[Role.ADMIN])
        self.client.post(reverse("school_year_create"), {
            "name": "2027", "start_date": "2027-02-01", "end_date": "2027-12-01", "is_current": "on",
        })
        atual.refresh_from_db()
        self.assertFalse(atual.is_current)
        self.assertTrue(SchoolYear.objects.get(name="2027").is_current)


class StudentChoicesTests(Round2Base):
    """O professor escolhe só entre os estudantes das próprias turmas."""

    def setUp(self):
        super().setUp()
        self.carla = Student.objects.create(school=self.school, first_name="Carla", last_name="Fora")

    def test_teacher_lists_only_own_students(self):
        self.login(self.prof)
        for name in ("pedagogy:occurrence_create", "pedagogy:observation_create"):
            page = self.client.get(reverse(name))
            choices = list(page.context["form"].fields["student"].queryset)
            self.assertIn(self.ana, choices, name)
            self.assertNotIn(self.carla, choices, name)

    def test_coordination_still_sees_the_school(self):
        self.login(self.users[Role.COORDENACAO])
        page = self.client.get(reverse("pedagogy:occurrence_create"))
        self.assertIn(self.carla, list(page.context["form"].fields["student"].queryset))


class JustificationNoticeTests(Round2Base):
    def test_secretaria_is_notified_of_new_justification(self):
        from apps.communication.models import Notification

        self.login(self.users[Role.RESPONSAVEL])
        hoje = timezone.localdate().isoformat()
        self.client.post(reverse("pedagogy:justification_create") + f"?estudante={self.ana.pk}", {
            "student_id": self.ana.pk, "start_date": hoje, "end_date": hoje, "reason": "Consulta médica",
        })
        aviso = Notification.objects.get(user=self.users[Role.SECRETARIA])
        self.assertIn("Ana", aviso.title)
        self.assertIn("Consulta médica", aviso.body)
        # Só a secretaria analisa: ninguém mais recebe.
        self.assertEqual(Notification.objects.count(), 1)


class ForgotPasswordHelpTests(Round2Base):
    """A ajuda manda cada perfil a quem de fato pode redefinir a senha dele."""

    def test_each_role_gets_one_correct_answer(self):
        from apps.core.passwords import can_reset_password

        for role, user in self.users.items():
            self.login(user)
            body = self.client.get(reverse("help")).content.decode()
            self.assertEqual(body.count("Esqueci minha senha."), 1, role)
            self.assertIn("códigos de recuperação", body, role)  # todos podem recuperar sem a escola
            if can_reset_password(self.users[Role.SECRETARIA], user) or role == Role.ESTUDANTE:
                self.assertIn("procure a secretaria", body.lower(), role)
            else:
                self.assertNotIn("procure a secretaria", body.lower(), role)


class FamilyOwnContactTests(Round2Base):
    def test_family_reaches_and_updates_own_contact(self):
        from apps.registry.models import GuardianProfile

        fam = self.users[Role.RESPONSAVEL]
        self.login(fam)
        url = reverse("guardian_profile", args=[fam.pk])
        self.assertContains(self.client.get(reverse("home")), f'href="{url}"')
        self.client.post(url, {"phone": "(11) 99999-0000", "emergency_contact": "Avó Lúcia",
                               "comm_preference": GuardianProfile._meta.get_field("comm_preference").default})
        self.assertEqual(GuardianProfile.objects.get(user=fam).emergency_contact, "Avó Lúcia")

    def test_staff_menu_has_no_family_link(self):
        self.login(self.prof)
        self.assertNotContains(self.client.get(reverse("home")), "Meus dados de contato")


class FutureDatesTests(Round2Base):
    def test_occurrence_cannot_be_in_the_future(self):
        self.login(self.prof)
        amanha = (timezone.localdate() + timedelta(days=1)).isoformat()
        resp = self.client.post(reverse("pedagogy:occurrence_create"), {
            "student": self.ana.pk, "date": amanha, "description": "Teste", "status": "aberta",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "não pode ter data futura")
        self.assertFalse(Occurrence.objects.exists())

    def test_birth_date_cannot_be_in_the_future(self):
        self.login(self.users[Role.SECRETARIA])
        amanha = (timezone.localdate() + timedelta(days=1)).isoformat()
        resp = self.client.post(reverse("student_edit", args=[self.ana.pk]), {
            "first_name": "Ana", "last_name": "Souza", "birth_date": amanha, "status": self.ana.status,
        })
        self.assertContains(resp, "não pode ser futura")
        self.ana.refresh_from_db()
        self.assertIsNone(self.ana.birth_date)
