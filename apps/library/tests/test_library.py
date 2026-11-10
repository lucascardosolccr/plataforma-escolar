"""Biblioteca escolar: empréstimo com regras, fila de reserva, renovação, lembretes e quem vê o quê."""

import datetime as dt

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification
from apps.communication.tests.test_communication import CommunicationBase
from apps.core.models import Role
from apps.registry.models import GuardianLink

from .. import services
from ..access import settings_for
from ..models import Book, Loan, Reservation


class LibraryBase(CommunicationBase):
    def setUp(self):
        super().setUp()
        self.book = Book.objects.create(school=self.school, title="O Pequeno Príncipe", author="Saint-Exupéry",
                                        copies=1)
        self.today = timezone.localdate()
        self.resp_bea = get_user_model().objects.create_user("resp_bea", password="senha-forte-1",
                                                             role=Role.RESPONSAVEL, school=self.school)
        GuardianLink.objects.create(school=self.school, guardian=self.resp_bea, student=self.bea, status="aprovado")

    def lend(self, student, book=None, user="sec"):
        self.login(user)
        return self.client.post(reverse("library:lend", args=[(book or self.book).pk]), {"estudante": student.pk})


class DueDateTests(LibraryBase):
    def test_due_date_skips_the_weekend_and_days_without_classes(self):
        friday = dt.date(2026, 11, 13)
        self.assertEqual(services.due_date(self.school, friday, 1), dt.date(2026, 11, 16))  # sábado → segunda
        from apps.school_calendar.models import CalendarEvent

        self.year.start_date, self.year.end_date, self.year.is_current = dt.date(2026, 2, 2), dt.date(2026, 12, 18), True
        self.year.save()
        CalendarEvent.objects.create(school=self.school, title="Feriado", kind="feriado", start=dt.date(2026, 11, 16),
                                     no_classes=True)
        self.assertEqual(services.due_date(self.school, friday, 3), dt.date(2026, 11, 17))  # segunda é feriado


class LendTests(LibraryBase):
    def test_lend_sets_due_date_and_tells_the_family(self):
        self.lend(self.ana)
        loan = Loan.objects.get()
        self.assertEqual(loan.due_on, services.due_date(self.school, self.today, 14))
        n = Notification.objects.get(user=self.resp, title__startswith="Livro emprestado")
        self.assertEqual(n.kind, "biblioteca")
        self.assertIn(f"{loan.due_on:%d/%m/%Y}", n.body)

    def test_rules_one_copy_limit_and_late_book_blocks(self):
        self.lend(self.ana)
        self.assertContains(self.lend(self.bea), "Nenhum exemplar livre", status_code=200)
        other = Book.objects.create(school=self.school, title="Dom Casmurro", copies=2)
        cfg = settings_for(self.school)
        cfg.max_loans = 1
        cfg.save()
        self.assertContains(self.lend(self.ana, other), "o limite da escola")
        cfg.max_loans = 3
        cfg.save()
        Loan.objects.filter(student=self.ana).update(due_on=self.today - dt.timedelta(days=2))
        self.assertContains(self.lend(self.ana, other), "atrasado desde")
        self.assertEqual(Loan.objects.count(), 1)

    def test_only_operators_lend_and_teacher_can_be_made_librarian(self):
        self.assertEqual(self.lend(self.ana, user="prof").status_code, 403)
        settings_for(self.school).librarians.add(self.prof)
        self.lend(self.ana, user="prof")
        self.assertEqual(Loan.objects.get().lent_by, self.prof)
        self.login("resp")
        self.assertEqual(self.client.get(reverse("library:desk")).status_code, 403)
        self.assertEqual(self.client.get(reverse("library:book_create")).status_code, 403)

    def test_other_school_cannot_see_the_book(self):
        self.client.login(username="prof_b", password="senha-forte-1")
        self.assertEqual(self.client.get(reverse("library:book", args=[self.book.pk])).status_code, 404)


class QueueTests(LibraryBase):
    def test_reserve_return_promotes_first_in_line_and_hold_expires(self):
        self.lend(self.ana)
        self.login("resp_bea")
        self.assertContains(self.client.get(reverse("library:book", args=[self.book.pk])), "Entrar na fila")
        self.client.post(reverse("library:reserve", args=[self.book.pk]), {"estudante": self.bea.pk})
        r = Reservation.objects.get()
        self.assertEqual(services.queue_position(r), 1)
        self.login("resp")  # não pode reservar pela filha de outra família
        self.assertEqual(self.client.post(reverse("library:reserve", args=[self.book.pk]),
                                          {"estudante": self.bea.pk}).status_code, 403)
        # Devolução: separa para a Beatriz e avisa; ninguém mais consegue pegar o exemplar.
        self.login("sec")
        self.client.post(reverse("library:give_back", args=[Loan.objects.get().pk]), {"estado": "capa dobrada"})
        r.refresh_from_db()
        self.assertEqual(r.status, "separado")
        self.assertTrue(Notification.objects.filter(user=self.resp_bea, title__startswith="Livro reservado").exists())
        self.assertContains(self.lend(self.ana), "Nenhum exemplar livre")
        self.assertEqual(Loan.objects.get(returned_at__isnull=False).condition_note, "capa dobrada")
        # Não retirou no prazo: a reserva expira e o exemplar volta à estante.
        services.daily(r.expires_on + dt.timedelta(days=1))
        r.refresh_from_db()
        self.assertEqual(r.status, "expirada")
        self.assertEqual(services.available(self.book), 1)

    def test_held_book_goes_to_who_reserved(self):
        self.lend(self.ana)
        services.reserve(self.book, self.bea, self.resp_bea)
        services.give_back(Loan.objects.get(), self.sec)
        self.lend(self.bea)
        self.assertEqual(Loan.objects.filter(returned_at__isnull=True).get().student, self.bea)
        self.assertEqual(Reservation.objects.get().status, "atendida")

    def test_cannot_reserve_when_a_copy_is_free(self):
        with self.assertRaisesMessage(services.LibraryError, "Há exemplar livre"):
            services.reserve(self.book, self.bea, self.resp_bea)


class RenewAndRemindTests(LibraryBase):
    def test_family_renews_once_but_not_with_queue_or_late(self):
        self.lend(self.ana)
        loan = Loan.objects.get()
        self.login("resp")
        self.client.post(reverse("library:renew", args=[loan.pk]))
        loan.refresh_from_db()
        self.assertEqual(loan.renewals, 1)
        self.client.post(reverse("library:renew", args=[loan.pk]))
        loan.refresh_from_db()
        self.assertEqual(loan.renewals, 1)  # só 1 renovação pelas regras padrão
        cfg = settings_for(self.school)
        cfg.max_renewals = 3
        cfg.save()
        services.reserve(self.book, self.bea, self.resp_bea)
        with self.assertRaisesMessage(services.LibraryError, "fila"):
            services.renew(loan, self.resp)
        self.login("resp_bea")  # outra família não renova o livro da Ana
        self.assertEqual(self.client.post(reverse("library:renew", args=[loan.pk])).status_code, 403)

    def test_reminder_the_day_before_and_overdue_weekly(self):
        self.lend(self.ana)
        loan = Loan.objects.get()
        Loan.objects.filter(pk=loan.pk).update(due_on=self.today + dt.timedelta(days=1))
        services.daily(self.today)
        services.daily(self.today)  # sem repetir
        self.assertEqual(Notification.objects.filter(user=self.resp, title__startswith="Devolver amanhã").count(), 1)
        Loan.objects.filter(pk=loan.pk).update(due_on=self.today - dt.timedelta(days=1))
        services.daily(self.today)
        late = Notification.objects.get(user=self.resp, title__startswith="Livro atrasado")
        self.assertEqual(late.priority, "importante")
        Loan.objects.filter(pk=loan.pk).update(due_on=self.today - dt.timedelta(days=3))
        services.daily(self.today)  # 3 dias: não insiste
        self.assertEqual(Notification.objects.filter(user=self.resp, title__startswith="Livro atrasado").count(), 1)
        self.login("resp")
        self.assertContains(self.client.get(reverse("pending_center")), "Livros da biblioteca atrasados")

    def test_reminders_are_part_of_the_daily_run(self):
        from apps.communication.reminders import run_daily

        self.lend(self.ana)
        Loan.objects.update(due_on=self.today + dt.timedelta(days=1))
        run = run_daily(self.today)
        self.assertIn("biblioteca: 1", run.detail)


class PrivacyAndPagesTests(LibraryBase):
    def test_mine_shows_only_own_children_and_history(self):
        self.lend(self.ana)
        services.give_back(Loan.objects.get(), self.sec)
        self.login("resp")
        page = self.client.get(reverse("library:mine"))
        self.assertContains(page, "1 livro lido")
        self.assertContains(page, "O Pequeno Príncipe")
        self.login("resp_bea")
        self.assertNotContains(self.client.get(reverse("library:mine")), "O Pequeno Príncipe")
        self.login("prof")  # o professor não vê a lista de quem pegou o livro
        self.assertNotContains(self.client.get(reverse("library:book", args=[self.book.pk])), "Ana")

    def test_catalog_search_and_free_filter(self):
        Book.objects.create(school=self.school, title="Dom Casmurro", author="Machado de Assis", copies=1)
        self.lend(self.ana)
        self.login("resp")
        page = self.client.get(reverse("library:catalog") + "?q=machado")
        self.assertContains(page, "Dom Casmurro")
        self.assertNotContains(page, "Pequeno")
        free = self.client.get(reverse("library:catalog") + "?livres=1")
        self.assertContains(free, "Dom Casmurro")
        self.assertNotContains(free, "Pequeno Príncipe")

    def test_fewer_copies_than_lent_is_refused(self):
        Book.objects.filter(pk=self.book.pk).update(copies=2)
        self.lend(self.ana)
        self.lend(self.bea)
        data = {"title": self.book.title, "author": self.book.author, "category": "infantil", "copies": 1,
                "active": "on"}
        self.assertContains(self.client.post(reverse("library:book_edit", args=[self.book.pk]), data),
                            "emprestado(s) agora")

    def test_import_csv_without_duplicates(self):
        self.login("sec")
        csv_text = ("título;autor;exemplares;tipo;estante\nDom Casmurro;Machado de Assis;3;literatura;A2\n"
                    "O Pequeno Príncipe;Saint-Exupéry;2;infantil;B1\nTurma da Mônica;Mauricio de Sousa;x;gibi;C\n"
                    "Turma da Mônica 2;Mauricio de Sousa;;gibi;C\n")
        f = SimpleUploadedFile("acervo.csv", csv_text.encode("cp1252"), content_type="text/csv")
        page = self.client.post(reverse("library:import"), {"file": f})
        self.assertContains(page, "2 livros cadastrados")
        self.assertContains(page, "1 já estava")
        self.assertContains(page, "Linha 4")
        dom = Book.objects.get(title="Dom Casmurro")
        self.assertEqual((dom.copies, dom.category, dom.location), (3, "literatura", "A2"))
        self.assertEqual(Book.objects.get(title="Turma da Mônica 2").category, "hq")


class SearchTests(LibraryBase):
    def test_student_search_shows_the_class_to_tell_namesakes_apart(self):
        self.login("sec")
        page = self.client.get(reverse("library:lend", args=[self.book.pk]) + "?q=ana")
        self.assertContains(page, self.turma.name)
        self.assertNotContains(page, "Beatriz")
