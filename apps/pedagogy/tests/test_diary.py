"""Diário de classe: o conteúdo de cada aula, com observações só da equipe."""

import datetime as dt

from django.urls import reverse
from django.utils import timezone

from apps.communication.tests.test_communication import CommunicationBase
from apps.pedagogy.models import LessonRecord


class DiaryTests(CommunicationBase):
    def _post(self, **extra):
        data = {"pair": f"{self.turma.pk}:{self.mat.pk}", "date": timezone.localdate().isoformat(),
                "content": "Frações equivalentes com tiras de papel.", "notes": "Três alunos precisaram de apoio.",
                "curriculum_codes": ""}
        data.update(extra)
        return self.client.post(reverse("pedagogy:diary_create"), data)

    def test_teacher_records_and_family_reads_content_but_not_team_notes(self):
        self.login("prof")
        self.assertRedirects(self._post(), reverse("pedagogy:diary_list"))
        rec = LessonRecord.objects.get()
        self.assertEqual((rec.teacher, rec.class_group, rec.subject), (self.prof, self.turma, self.mat))
        self.login("resp")  # responsável da Ana, do 1º Ano A
        page = self.client.get(reverse("pedagogy:diary_list"))
        self.assertContains(page, "Frações equivalentes")
        self.assertNotContains(page, "Três alunos precisaram de apoio")
        self.assertNotContains(page, reverse("pedagogy:diary_edit", args=[rec.pk]))
        self.login("coord")
        self.assertContains(self.client.get(reverse("pedagogy:diary_list")), "Três alunos precisaram de apoio")

    def test_refuses_future_duplicate_and_other_class(self):
        self.login("prof")
        self._post(date=(timezone.localdate() + dt.timedelta(days=1)).isoformat())
        self.assertFalse(LessonRecord.objects.exists())
        self._post()
        resp = self._post(content="De novo")
        self.assertContains(resp, "Esta aula já tem registro")
        self._post(pair=f"{self.turma_b.pk}:{self.mat.pk}", date="2026-03-02")
        self.assertEqual(LessonRecord.objects.count(), 1)

    def test_edit_only_by_teacher_of_the_pair_and_no_access_for_office(self):
        self.login("prof")
        self._post()
        rec = LessonRecord.objects.get()
        url = reverse("pedagogy:diary_edit", args=[rec.pk])
        self.client.post(url, {"date": rec.date.isoformat(), "content": "Corrigido", "notes": "", "curriculum_codes": ""})
        rec.refresh_from_db()
        self.assertEqual(rec.content, "Corrigido")
        for user, code in (("coord", 403), ("sec", 403), ("resp", 403)):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, code, user)
        self.login("sec")
        self.assertEqual(self.client.get(reverse("pedagogy:diary_list")).status_code, 403)
        self.login("resp_b")  # família de outra escola não vê nada
        self.assertNotContains(self.client.get(reverse("pedagogy:diary_list")), "Corrigido")

    def test_skills_from_the_diary_count_as_worked(self):
        from apps.curriculum.models import CurriculumItem
        from apps.curriculum.services import coverage

        item = CurriculumItem.objects.filter(code__startswith="EF01MA").first()
        self.assertIsNotNone(item)
        self.login("prof")
        self._post(curriculum_codes=item.code)
        self.assertIn(item, LessonRecord.objects.get().curriculum.all())
        self.turma.school_year.start_date = timezone.localdate() - dt.timedelta(days=30)
        self.turma.school_year.save()
        cov = coverage(self.turma, self.mat)
        self.assertGreaterEqual(cov["counts"]["worked"], 1)


class DiaryCalendarTests(CommunicationBase):
    """Com o calendário oficial publicado, o diário não aceita aula em dia sem aula."""

    _post = DiaryTests._post

    def test_school_calendar_is_respected_when_published(self):
        from apps.school_calendar.models import CalendarEvent, CalendarPublication

        year = self.turma.school_year
        year.start_date, year.end_date = dt.date(2026, 2, 2), dt.date(2026, 12, 18)
        year.save()
        CalendarPublication.objects.create(school_year=year)
        CalendarEvent.objects.create(school=self.school, school_year=year, kind="feriado", title="Feriado",
                                     start=dt.date(2026, 4, 21), no_classes=True)
        CalendarEvent.objects.create(school=self.school, school_year=year, kind="letivo_extra", title="Reposição",
                                     start=dt.date(2026, 5, 9))
        self.login("prof")
        self.assertContains(self._post(date="2026-05-10"), "não teve aula")       # domingo
        self.assertContains(self._post(date="2026-04-21"), "não teve aula")       # feriado
        self.assertContains(self._post(date="2026-01-20"), "fora do ano letivo")  # antes do início
        self._post(date="2026-05-09")                                             # sábado de reposição
        self._post(date="2026-05-11")                                             # segunda comum
        self.assertEqual(sorted(LessonRecord.objects.values_list("date", flat=True)),
                         [dt.date(2026, 5, 9), dt.date(2026, 5, 11)])
