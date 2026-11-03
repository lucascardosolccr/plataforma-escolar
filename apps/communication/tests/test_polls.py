"""Consultas às famílias: um voto por responsável, totais para a equipe, nunca quem votou em quê."""

import datetime as dt

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditLog, Role
from apps.registry.models import GuardianLink

from ..models import Notification, Poll, PollVote
from .test_communication import CommunicationBase


class PollTests(CommunicationBase):
    def setUp(self):
        super().setUp()
        self.resp_bea = get_user_model().objects.create_user("resp_bea", password="senha-forte-1",
                                                             role=Role.RESPONSAVEL, school=self.school)
        GuardianLink.objects.create(school=self.school, guardian=self.resp_bea, student=self.bea, status="aprovado")
        self.deadline = (timezone.localdate() + dt.timedelta(days=5)).isoformat()

    def _create(self, user="prof", **extra):
        self.login(user)
        data = {"question": "Melhor horário para a reunião?", "description": "", "deadline": self.deadline,
                "options_text": "Terça às 19h\nSábado às 9h", "class_groups": [self.turma.pk], "show_results": "on"}
        data.update(extra)
        self.client.post(reverse("communication:poll_create"), data)
        return Poll.objects.filter(question=data["question"]).first()

    def _vote(self, poll, option):
        return self.client.post(reverse("communication:poll_vote", args=[poll.pk]), {"option": option})

    def test_teacher_poll_reaches_only_the_class_families_one_vote_each(self):
        poll = self._create()
        self.assertEqual(poll.options, ["Terça às 19h", "Sábado às 9h"])
        self.assertTrue(Notification.objects.filter(user=self.resp, title__startswith="Consulta:").exists())
        self.assertFalse(Notification.objects.filter(user=self.resp_bea, title__startswith="Consulta:").exists())
        self.login("resp")
        self.assertContains(self.client.get(reverse("pending_center")), "Consultas da escola aguardando")
        self._vote(poll, 0)
        self._vote(poll, 1)  # muda o voto: continua um só
        self.assertEqual(list(PollVote.objects.values_list("option", flat=True)), [1])
        self.assertNotContains(self.client.get(reverse("pending_center")), "Consultas da escola aguardando")
        self.assertIsNone(self.client.get(reverse("communication:poll_detail", args=[poll.pk])).context["results"])
        self.login("resp_bea")  # outra turma: não vê nem vota
        self.assertEqual(self.client.get(reverse("communication:poll_detail", args=[poll.pk])).status_code, 404)
        self.assertEqual(self._vote(poll, 0).status_code, 403)

    def test_staff_sees_totals_never_who_voted_what(self):
        self.resp.first_name, self.resp.last_name = "Marcelina", "Quaresma"
        self.resp.save()
        poll = self._create()
        self.login("resp")
        self._vote(poll, 1)
        self.login("prof")
        page = self.client.get(reverse("communication:poll_detail", args=[poll.pk]))
        self.assertEqual([r["n"] for r in page.context["results"]], [0, 1])
        self.assertContains(page, "1 família respondeu de 1 com acesso")
        self.assertNotContains(page, "Marcelina")  # nome de quem votou não aparece
        self.assertNotContains(page, "Quaresma")
        log = AuditLog.objects.get(detail__startswith="Respondeu à consulta")
        self.assertNotIn("Sábado", log.detail)  # nem na auditoria

    def test_results_to_families_only_after_closing_and_if_allowed(self):
        poll = self._create()
        hidden = self._create(question="Interesse em oficina?", show_results="")
        for p in (poll, hidden):
            self.client.post(reverse("communication:poll_close", args=[p.pk]))
        self.login("resp")
        self.assertIsNotNone(self.client.get(reverse("communication:poll_detail", args=[poll.pk])).context["results"])
        self.assertContains(self.client.get(reverse("communication:poll_detail", args=[hidden.pk])),
                            "optou por não divulgar")
        self._vote(poll, 0)
        self.assertFalse(PollVote.objects.exists())  # encerrada não recebe voto

    def test_whole_school_only_for_management_and_option_rules(self):
        self.assertIsNone(self._create(question="Escola toda pelo professor", class_groups=[]))
        poll = self._create(user="dir", question="Data da festa?", class_groups=[])
        self.assertIsNotNone(poll)
        self.login("resp_bea")  # escola toda: Beatriz é do 1º Ano B e a família vê
        self.assertEqual(self.client.get(reverse("communication:poll_detail", args=[poll.pk])).status_code, 200)
        self.assertIsNone(self._create(question="Uma opção só", options_text="Sim"))
        self.assertIsNone(self._create(question="Repetida", options_text="Sim\nsim"))
