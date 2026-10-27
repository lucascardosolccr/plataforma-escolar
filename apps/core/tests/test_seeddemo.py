"""A escola de demonstração é criada, não colide com a real e sai inteira.

O comando não tinha teste. Ele gerava nomes completos repetidos (três
"Alice Almeida" na mesma escola), o que confunde justamente quem está
conhecendo a plataforma pela demonstração.
"""

from collections import Counter

from django.core.management import call_command
from django.test import TestCase

from apps.core.models import School
from apps.registry.models import Enrollment, Student


class SeedDemoTests(TestCase):
    def test_creates_demo_with_unique_names_and_dated_enrollments(self):
        call_command("seeddemo", verbosity=0)
        school = School.objects.get(code="demo")
        nomes = Counter(s.full_name for s in Student.objects.filter(school=school))
        self.assertEqual(sum(nomes.values()), 72)
        self.assertEqual([n for n, q in nomes.items() if q > 1], [])
        # Matrículas nascem com a data de entrada (início do ano letivo).
        self.assertFalse(
            Enrollment.objects.filter(school=school, started_on__isnull=True).exists()
        )

    def test_clean_removes_only_the_demo_school(self):
        real = School.objects.create(name="Escola real", code="real")
        call_command("seeddemo", verbosity=0)
        call_command("seeddemo", "--limpar", verbosity=0)
        self.assertFalse(School.objects.filter(code="demo").exists())
        self.assertTrue(School.objects.filter(pk=real.pk).exists())
