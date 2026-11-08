"""Carteirinha (três formas de identificação) e portaria (entrada, atraso, saída, avisos e chamada)."""

import datetime as dt
import random
from unittest import mock
from zoneinfo import ZoneInfo

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification
from apps.communication.tests.test_communication import CommunicationBase
from apps.core.models import AuditLog
from apps.pedagogy.models import AttendanceRecord

from .. import services
from ..models import GateEvent, GateSettings, StudentCard
from ..symbols import code128_widths, qr_matrix

TZ = ZoneInfo(settings.TIME_ZONE)
WED = dt.date(2026, 11, 4)  # quarta-feira


def at(hour, minute, day=WED):
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=TZ)


class CodeTests(SimpleTestCase):
    def test_check_digit_catches_typos(self):
        rnd = random.Random(1)
        for _ in range(300):
            body = "".join(rnd.choice(services.ALPHABET) for _ in range(8))
            code = body + services._luhn32(body)
            self.assertTrue(services.valid_shape(code))
            i = rnd.randrange(8)
            wrong = rnd.choice([c for c in services.ALPHABET if c != code[i]])
            self.assertFalse(services.valid_shape(code[:i] + wrong + code[i + 1:]))  # um símbolo trocado
            if code[i] != code[i + 1]:
                swapped = code[:i] + code[i + 1] + code[i] + code[i + 2:]
                self.assertFalse(services.valid_shape(swapped), swapped)  # vizinhos invertidos

    def test_normalize_accepts_hyphens_lowercase_and_look_alikes(self):
        self.assertEqual(services.normalize(" 7k3m-q9xp-4 "), "7K3MQ9XP4")
        self.assertEqual(services.normalize("O1IL"), "0111")

    def test_symbols_have_the_expected_structure(self):
        widths = code128_widths("7K3MQ9XP4")
        self.assertEqual(sum(widths), 11 * (1 + 9 + 1) + 13)  # início, 9 caracteres, verificação e fim
        m = qr_matrix("EC1:7K3MQ9XP4:ABCDEFGHJK")
        self.assertEqual(len(m), 25)  # versão 2
        self.assertTrue(all(m[r][c] for r, c in ((0, 0), (0, 6), (6, 0), (6, 6))))  # cantos do localizador


class GateBase(CommunicationBase):
    def setUp(self):
        super().setUp()
        self.card = services.issue(self.ana, self.sec)

    def scan(self, raw, user=None, kind="entrada", origin="leitor", when=at(7, 25)):
        self.client.force_login(user or self.sec)
        with mock.patch("apps.gate.services.now", return_value=when):
            return self.client.post(reverse("gate:station"), {"codigo": raw, "tipo": kind, "origem": origin})

    def notes(self, text):
        return Notification.objects.filter(user=self.resp, title__contains=text)


class CardTests(GateBase):
    def test_three_forms_identify_the_same_card(self):
        payload = services.qr_payload(self.card)
        self.assertEqual(services.parse(payload), (self.card.code, GateEvent.Method.QR))
        self.assertEqual(services.parse(self.card.display_code.lower()), (self.card.code, None))
        forged = payload[:-1] + ("A" if payload[-1] != "A" else "B")
        self.assertIsNone(services.parse(forged)[0])  # assinatura não confere

    def test_family_sees_own_child_card_others_do_not(self):
        url = reverse("gate:card", args=[self.ana.pk])
        self.client.force_login(self.resp)
        page = self.client.get(url)
        self.assertContains(page, self.card.display_code)
        self.assertContains(page, 'class="qrcode"')
        self.assertContains(page, 'class="barcode"')
        self.assertTrue(AuditLog.objects.filter(detail__startswith="Abriu a carteirinha digital").exists())
        self.assertEqual(self.client.get(reverse("gate:card", args=[self.bea.pk])).status_code, 403)
        self.client.force_login(self.prof)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_second_copy_needs_reason_and_old_card_is_refused(self):
        self.client.force_login(self.sec)
        self.client.post(reverse("gate:card_issue", args=[self.ana.pk]), {"motivo": ""})
        self.assertEqual(StudentCard.objects.filter(student=self.ana).count(), 1)
        self.client.post(reverse("gate:card_issue", args=[self.ana.pk]), {"motivo": "Perdeu"})
        old = self.card
        old.refresh_from_db()
        self.assertFalse(old.active)
        page = self.scan(old.code)
        self.assertContains(page, "Carteirinha cancelada")
        self.assertFalse(GateEvent.objects.exists())
        self.assertTrue(AuditLog.objects.filter(detail__startswith="Portaria: leitura recusada").exists())

    def test_class_batch_issues_missing_cards(self):
        self.client.force_login(self.sec)
        self.client.post(reverse("gate:class_cards", args=[self.turma_b.pk]))
        self.assertTrue(StudentCard.objects.filter(student=self.bea, revoked_at__isnull=True).exists())
        page = self.client.get(reverse("gate:class_cards", args=[self.turma_b.pk]) + "?imprimir=1")
        self.assertContains(page, 'class="id-card id-card-front"')
        self.client.force_login(self.coord)
        self.assertEqual(self.client.get(reverse("gate:cards")).status_code, 403)


class StationTests(GateBase):
    def test_on_time_entry_notifies_once_and_fills_attendance(self):
        page = self.scan(self.card.code)
        self.assertContains(page, "Entrada registrada às 07:25")
        event = GateEvent.objects.get()
        self.assertEqual((event.method, event.late), ("barras", False))
        self.assertEqual(self.notes("chegou à escola às 07:25").count(), 1)
        self.assertEqual(AttendanceRecord.objects.get(student=self.ana, date=WED).status, "presente")
        self.assertContains(self.scan(services.qr_payload(self.card), when=at(7, 40)), "já registrada hoje às 07:25")
        self.assertEqual(GateEvent.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.resp, kind="portaria").count(), 1)

    def test_late_beyond_tolerance_registers_and_notifies(self):
        self.scan(self.card.display_code, origin="teclado", when=at(7, 52))
        event = GateEvent.objects.get()
        self.assertEqual((event.method, event.late, event.minutes_late), ("codigo", True, 22))
        self.assertEqual(self.notes("com 22 minutos de atraso").count(), 1)
        self.assertFalse(self.notes("chegou à escola às 07:52,").exclude(title__contains="atraso").exists())
        self.assertEqual(AttendanceRecord.objects.get(student=self.ana, date=WED).status, "atraso")

    def test_within_tolerance_is_not_late_and_direction_sets_times(self):
        self.scan(self.card.code, when=at(7, 40))  # 07:30 + 10 min
        self.assertFalse(GateEvent.objects.get().late)
        self.client.force_login(self.direc)
        self.client.post(reverse("gate:settings"), {"entry_morning": "07:00", "entry_afternoon": "13:00",
                                                    "entry_full": "07:30", "entry_night": "19:00", "tolerance": 5,
                                                    "fill_attendance": "on"})
        self.assertEqual(GateSettings.for_school(self.school).tolerance, 5)
        GateEvent.objects.all().delete()
        self.scan(self.card.code, when=at(7, 6))
        self.assertEqual(GateEvent.objects.get().minutes_late, 6)
        self.client.force_login(self.sec)
        self.assertEqual(self.client.get(reverse("gate:settings")).status_code, 403)

    def test_absence_already_marked_becomes_late_teacher_presence_is_kept(self):
        AttendanceRecord.objects.create(school=self.school, class_group=self.turma, student=self.ana, date=WED,
                                        status="falta", recorded_by=self.prof)
        self.scan(self.card.code, when=at(8, 30))
        self.assertEqual(AttendanceRecord.objects.get(student=self.ana, date=WED).status, "atraso")
        self.assertTrue(AuditLog.objects.filter(detail__contains="a falta do dia virou atraso").exists())

    def test_each_form_registers_entry_and_time_at_the_station(self):
        """Pedido de 08/11/2026: QR Code, código de barras e código digitado registram a entrada e o horário."""
        thu = WED + dt.timedelta(days=1)
        page = self.scan(services.qr_payload(self.card), when=at(7, 20))
        self.assertContains(page, "Entrada registrada às 07:20 (QR Code)")
        self.assertContains(self.scan(self.card.code, kind="saida", when=at(12, 5)),
                            "Saída registrada às 12:05 (código de barras)")
        self.assertContains(self.scan(self.card.display_code, origin="teclado", when=at(7, 22, thu)),
                            "Entrada registrada às 07:22 (código digitado)")
        got = [(e.kind, e.method, timezone.localtime(e.at).strftime("%d %H:%M"))
               for e in GateEvent.objects.order_by("at")]
        self.assertEqual(got, [("entrada", "qr", f"{WED.day:02d} 07:20"), ("saida", "barras", f"{WED.day:02d} 12:05"),
                               ("entrada", "codigo", f"{thu.day:02d} 07:22")])

    def test_weekend_entry_is_never_late_and_exit_notifies(self):
        sat = WED + dt.timedelta(days=3)
        self.scan(self.card.code, when=at(9, 0, sat))
        self.assertFalse(GateEvent.objects.get().late)
        self.scan(self.card.code, kind="saida", when=at(12, 0, sat))
        self.assertEqual(self.notes("saiu da escola às 12:00").count(), 1)

    def test_invalid_input_and_other_school_are_refused(self):
        self.assertContains(self.scan("ABCD-EFGH-9"), "Código inválido")
        self.assertContains(self.scan("EC1:" + self.card.code + ":AAAAAAAAAA"), "assinatura inválida")
        self.assertEqual(self.scan(self.card.code, user=self.other_prof).status_code, 403)
        self.assertFalse(GateEvent.objects.exists())

    def test_manual_entry_and_today_panel(self):
        self.client.force_login(self.sec)
        with mock.patch("apps.gate.services.now", return_value=at(7, 20)):
            self.client.post(reverse("gate:station"), {"estudante": self.bea.pk, "tipo": "entrada"})
        self.assertEqual(GateEvent.objects.get().method, "manual")
        self.scan(self.card.code, when=at(7, 55))
        page = self.client.get(reverse("gate:today") + "?dia=2026-11-04")
        self.assertContains(page, "2 chegadas registradas, 1 com atraso")
        self.client.force_login(self.resp)
        self.assertContains(self.client.get(reverse("gate:history", args=[self.ana.pk])), "Atraso de 25 min")
        self.assertContains(self.client.get(reverse("gate:mine")), self.card.display_code)
        self.assertEqual(self.client.get(reverse("gate:station")).status_code, 403)


class IntegrationTests(GateBase):
    def test_repeated_late_arrivals_become_an_early_signal(self):
        from apps.cognitio.trajectory import class_overview

        for k in range(3):
            services.register(self.ana, "entrada", "barras", self.sec, card=self.card, when=at(8, 0, WED - dt.timedelta(days=k)))
        rows = class_overview(self.turma, WED - dt.timedelta(days=60), WED, today=WED)["rows"]
        ana = next(r for r in rows if r["student"] == self.ana)
        self.assertIn("pontualidade", [i["key"] for i in ana["indicators"]])

    def test_secretaria_is_reminded_of_students_without_card(self):
        self.client.force_login(self.sec)
        self.assertContains(self.client.get(reverse("pending_center")), "Estudantes ativos sem carteirinha")

    def test_simultaneous_reads_do_not_crash_or_notify_twice(self):
        services.register(self.ana, "entrada", "barras", self.sec, card=self.card, when=at(7, 20))
        # Simula a corrida: a conferência "já existe?" não vê o registro que a outra leitura acabou de gravar.
        with mock.patch.object(services.GateEvent.objects, "filter") as check:
            check.return_value.first.return_value = None
            event, existed = services.register(self.ana, "entrada", "qr", self.sec, card=self.card, when=at(7, 21))
        self.assertTrue(existed)
        self.assertEqual((GateEvent.objects.count(), event.at.minute), (1, 20))
        self.assertEqual(Notification.objects.filter(user=self.resp, kind="portaria").count(), 1)



class RestrictedCoordinationGateTests(GateBase):
    coordenacao_restrita = True

    def test_restricted_coordination_sees_only_students_of_the_designation(self):
        from django.utils import timezone

        from apps.coordination.models import CoordinatorAssignment

        CoordinatorAssignment.objects.create(school=self.school, coordinator=self.coord,
                                             starts_on=timezone.localdate()).class_groups.add(self.turma)
        self.client.force_login(self.coord)
        self.assertEqual(self.client.get(reverse("gate:history", args=[self.ana.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("gate:history", args=[self.bea.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("gate:card", args=[self.bea.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("gate:station")).status_code, 200)  # a portaria segue aberta

    def test_restricted_coordination_cannot_edit_a_student_outside_the_designation(self):
        from django.utils import timezone

        from apps.coordination.models import CoordinatorAssignment

        CoordinatorAssignment.objects.create(school=self.school, coordinator=self.coord,
                                             starts_on=timezone.localdate()).class_groups.add(self.turma)
        self.client.force_login(self.coord)
        self.assertEqual(self.client.get(reverse("student_edit", args=[self.bea.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("student_edit", args=[self.bea.pk]),
                                          {"first_name": "Alterada"}).status_code, 403)

    def test_restricted_coordination_cannot_edit_observations_outside_the_designation(self):
        from django.utils import timezone

        from apps.coordination.models import CoordinatorAssignment
        from apps.pedagogy.models import PedagogicalObservation

        CoordinatorAssignment.objects.create(school=self.school, coordinator=self.coord,
                                             starts_on=timezone.localdate()).class_groups.add(self.turma)
        mine = PedagogicalObservation.objects.create(school=self.school, student=self.ana, teacher=self.prof,
                                                     subject=self.mat, content="Frações")
        other = PedagogicalObservation.objects.create(school=self.school, student=self.bea, teacher=self.prof,
                                                      subject=self.mat, content="Leitura")
        self.client.force_login(self.coord)
        self.assertEqual(self.client.get(reverse("pedagogy:observation_edit", args=[mine.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("pedagogy:observation_edit", args=[other.pk])).status_code, 403)


class EnteredButAbsentTests(GateBase):
    def test_gate_entry_with_absence_in_class_is_flagged(self):
        services.register(self.ana, "entrada", "barras", self.sec, card=self.card, when=at(7, 20))
        self.assertEqual(services.entered_but_absent(self.school, WED), [])  # a chegada marcou presente
        AttendanceRecord.objects.filter(student=self.ana, date=WED).update(status="falta")  # o professor, depois
        found = services.entered_but_absent(self.school, WED)
        self.assertEqual([m["entry"].student for m in found], [self.ana])
        self.client.force_login(self.direc)
        self.assertContains(self.client.get(reverse("gate:today") + "?dia=2026-11-04"),
                            "Entraram na escola e estão com falta na chamada")
        self.assertEqual(services.entered_but_absent(self.school, WED, class_ids={self.turma_b.pk}), [])


class MissingEntryTests(GateBase):
    def missing(self, when):
        return services.notify_missing(self.school, when)

    def notes_missing(self):
        return Notification.objects.filter(user=self.resp, dedupe_key__startswith="sem-entrada:")

    def test_off_by_default_and_only_inside_the_window_on_school_days(self):
        self.assertEqual(self.missing(at(8, 5)), 0)  # desligado
        cfg = GateSettings.for_school(self.school)
        cfg.notify_missing_after = 30
        cfg.save()
        self.assertEqual(self.missing(at(7, 55)), 0)  # antes de 07:30 + 30 min
        self.assertEqual(self.missing(at(12, 0)), 0)  # passou da janela de 3 horas
        self.assertEqual(self.missing(at(8, 5, WED + dt.timedelta(days=3))), 0)  # sábado
        self.missing(at(8, 5))
        self.assertEqual(self.notes_missing().count(), 1)
        self.assertIn("Ainda não registramos a chegada de Ana", self.notes_missing().get().title)
        self.missing(at(8, 20))
        self.assertEqual(self.notes_missing().count(), 1)  # uma vez por dia

    def test_entry_attendance_or_justification_prevent_the_notice(self):
        from apps.pedagogy.models import AbsenceJustification

        cfg = GateSettings.for_school(self.school)
        cfg.notify_missing_after = 30
        cfg.save()
        services.register(self.ana, "entrada", "barras", self.sec, card=self.card, when=at(7, 20))
        self.missing(at(8, 5))
        self.assertFalse(self.notes_missing().exists())
        GateEvent.objects.all().delete()
        AttendanceRecord.objects.filter(student=self.ana).update(status="presente")  # o professor viu na sala
        self.missing(at(8, 5))
        self.assertFalse(self.notes_missing().exists())
        AttendanceRecord.objects.all().delete()
        AbsenceJustification.objects.create(school=self.school, student=self.ana, class_group=self.turma,
                                            start_date=WED, end_date=WED, submitted_by=self.resp, reason="Consulta")
        self.missing(at(8, 5))
        self.assertFalse(self.notes_missing().exists())

    def test_direction_turns_it_on_with_a_sane_range(self):
        self.client.force_login(self.direc)
        base = {"entry_morning": "07:30", "entry_afternoon": "13:00", "entry_full": "07:30", "entry_night": "19:00",
                "tolerance": 10, "fill_attendance": "on"}
        page = self.client.post(reverse("gate:settings"), {**base, "notify_missing_after": 5})
        self.assertContains(page, "Use de 15 a 240 minutos")
        self.client.post(reverse("gate:settings"), {**base, "notify_missing_after": 45})
        self.assertEqual(GateSettings.for_school(self.school).notify_missing_after, 45)
